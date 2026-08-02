"""Bounded continuous capture, enhancement, VAD and recognition pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Final, Protocol, cast

from mic.asr import AsrEndpoint
from mic.asr_runtime import FrameAnalysis
from mic.camplusplus import (
    CamPlusPlusEmbedding,
    CamPlusPlusStreamingProcessor,
    CamPlusPlusWindow,
)
from mic.speech_models import ZipEnhancerStreamingProcessor

RAW_QUEUE_MAX_FRAMES: Final = 75
ENDPOINT_QUEUE_MAX_SEGMENTS: Final = 2
CAMPP_QUEUE_MAX_WINDOWS: Final = 2
LOGGER = logging.getLogger(__name__)


class BlockCapture(Protocol):
    async def read_block(self) -> bytes | None: ...


class EndpointProcessor(Protocol):
    def analyze_enhanced_frame(self, frame: bytes, rtp_timestamp: int) -> FrameAnalysis: ...

    def push_enhanced_frame(
        self, frame: bytes, rtp_timestamp: int
    ) -> AsrEndpoint | None: ...

    def flush_enhanced_frames(self) -> AsrEndpoint | None: ...

    async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None: ...

    async def emit_voice_evidence(
        self, window: CamPlusPlusWindow, embedding: CamPlusPlusEmbedding, revision: str
    ) -> None: ...


class CamppModel(Protocol):
    revision: str

    def embed_pcm16le(self, pcm16le: bytes) -> CamPlusPlusEmbedding: ...


type TimestampedFrame = tuple[bytes, int]


async def run_continuous_pipeline(
    capture: BlockCapture,
    endpoint_processor: EndpointProcessor,
    *,
    start_timestamp: int,
    enhancer: ZipEnhancerStreamingProcessor | None = None,
    campp_streamer: CamPlusPlusStreamingProcessor | None = None,
    campp_model: CamppModel | None = None,
) -> None:
    """Keep capture active while serial workers enhance, endpoint and recognize audio."""
    raw_frames: asyncio.Queue[TimestampedFrame | None] = asyncio.Queue(
        maxsize=RAW_QUEUE_MAX_FRAMES
    )
    endpoints: asyncio.Queue[AsrEndpoint | None] = asyncio.Queue(
        maxsize=ENDPOINT_QUEUE_MAX_SEGMENTS
    )
    campp_windows: asyncio.Queue[CamPlusPlusWindow | None] = asyncio.Queue(
        maxsize=CAMPP_QUEUE_MAX_WINDOWS
    )

    async def capture_frames() -> None:
        timestamp = start_timestamp
        while (frame := await capture.read_block()) is not None:
            await raw_frames.put((frame, timestamp))
            timestamp = (timestamp + 320) % (1 << 32)
        await raw_frames.put(None)

    async def enhance_and_endpoint() -> None:
        last_timestamp: int | None = None
        while (item := await raw_frames.get()) is not None:
            frame, timestamp = item
            last_timestamp = timestamp
            enhanced_frames = (
                (frame,)
                if enhancer is None
                else await asyncio.to_thread(enhancer.push, frame)
            )
            first_timestamp = timestamp - 320 * (len(enhanced_frames) - 1)
            for index, enhanced_frame in enumerate(enhanced_frames):
                timestamp = (first_timestamp + index * 320) % (1 << 32)
                analysis = _analyze(endpoint_processor, enhanced_frame, timestamp)
                if campp_streamer is not None:
                    for window in campp_streamer.push(enhanced_frame, timestamp, speech=analysis.speech):
                        await campp_windows.put(window)
                if analysis.endpoint is not None:
                    await endpoints.put(analysis.endpoint)

        if enhancer is not None and last_timestamp is not None:
            tail = await asyncio.to_thread(enhancer.flush)
            first_timestamp = last_timestamp - 320 * (len(tail) - 1)
            for index, enhanced_frame in enumerate(tail):
                timestamp = (first_timestamp + index * 320) % (1 << 32)
                analysis = _analyze(endpoint_processor, enhanced_frame, timestamp)
                if campp_streamer is not None:
                    for window in campp_streamer.push(enhanced_frame, timestamp, speech=analysis.speech):
                        await campp_windows.put(window)
                if analysis.endpoint is not None:
                    await endpoints.put(analysis.endpoint)
        endpoint = endpoint_processor.flush_enhanced_frames()
        if endpoint is not None:
            await endpoints.put(endpoint)
        await endpoints.put(None)
        if campp_streamer is not None:
            campp_streamer.reset()
        await campp_windows.put(None)

    async def recognize() -> None:
        while (endpoint := await endpoints.get()) is not None:
            await endpoint_processor.recognize_endpoint(endpoint)

    async def process_campp() -> None:
        while (window := await campp_windows.get()) is not None:
            model = campp_model
            if model is None:
                continue
            try:
                started = perf_counter()
                embedding = await asyncio.to_thread(model.embed_pcm16le, window.pcm16le)
                await endpoint_processor.emit_voice_evidence(window, embedding, model.revision)
                LOGGER.debug(
                    "CAM++ evidence emitted",
                    extra={
                        "campp_latency_ms": (perf_counter() - started) * 1_000,
                        "campp_queue_depth": campp_windows.qsize(),
                        "speech_ms": window.speech_ms,
                    },
                )
            except Exception:
                LOGGER.exception(
                    "CAM++ window failed; discarding evidence",
                    extra={"speech_ms": window.speech_ms},
                )

    tasks = [
        asyncio.create_task(capture_frames()),
        asyncio.create_task(enhance_and_endpoint()),
        asyncio.create_task(recognize()),
        asyncio.create_task(process_campp()),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        if campp_streamer is not None:
            campp_streamer.reset()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _analyze(
    processor: EndpointProcessor, frame: bytes, rtp_timestamp: int
) -> FrameAnalysis:
    """Compatibility bridge while all test/control adapters adopt frame analysis."""
    method = getattr(processor, "analyze_enhanced_frame", None)
    if callable(method):
        return cast(Callable[[bytes, int], FrameAnalysis], method)(frame, rtp_timestamp)
    return FrameAnalysis(
        speech=False,
        endpoint=processor.push_enhanced_frame(frame, rtp_timestamp),
    )
