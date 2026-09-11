"""Bounded continuous capture, enhancement, VAD and recognition pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter
from typing import Final, Protocol, cast

from mic.asr import AsrEndpoint
from mic.asr_runtime import FrameAnalysis
from mic.camplusplus import (
    CamPlusPlusEmbedding,
    CamPlusPlusStreamingProcessor,
    CamPlusPlusWindow,
)
from mic.portaudio_capture import CaptureOverflowError
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


@dataclass(frozen=True, slots=True)
class _CaptureDiscontinuity:
    rtp_timestamp: int


async def run_continuous_pipeline(
    capture: BlockCapture,
    endpoint_processor: EndpointProcessor,
    *,
    start_timestamp: int,
    enhancer: ZipEnhancerStreamingProcessor | None = None,
    campp_streamer: CamPlusPlusStreamingProcessor | None = None,
    campp_model: CamppModel | None = None,
    session_id: str = "",
    trace_id: str = "",
    stream_id: str = "",
) -> None:
    """Keep capture active while serial workers enhance, endpoint and recognize audio."""
    raw_frames: asyncio.Queue[
        TimestampedFrame | _CaptureDiscontinuity | None
    ] = asyncio.Queue(maxsize=RAW_QUEUE_MAX_FRAMES)
    endpoints: asyncio.Queue[AsrEndpoint | None] = asyncio.Queue(
        maxsize=ENDPOINT_QUEUE_MAX_SEGMENTS
    )
    campp_windows: asyncio.Queue[CamPlusPlusWindow | None] = asyncio.Queue(
        maxsize=CAMPP_QUEUE_MAX_WINDOWS
    )

    def _offer_latest[T](
        queue: asyncio.Queue[T], item: T, kind: str, rtp_timestamp: int,
        payload: bytes = b"",
    ) -> None:
        """Evict only pending work; never make capture wait for a slow consumer."""
        if queue.full():
            _ = queue.get_nowait()
            LOGGER.debug(
                "mic_queue trace=%s session=%s stream=%s kind=%s "
                "rtp_timestamp=%d outcome=evicted_oldest",
                trace_id, session_id, stream_id, kind, rtp_timestamp,
            )
        queue.put_nowait(item)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "mic_queue trace=%s session=%s stream=%s kind=%s rtp_timestamp=%d "
                "codec=pcm16le bytes=%d digest=%s outcome=queued",
                trace_id, session_id, stream_id, kind, rtp_timestamp,
                len(payload), sha256(payload).hexdigest(),
            )

    async def capture_frames() -> None:
        timestamp = start_timestamp
        while True:
            try:
                frame = await capture.read_block()
            except CaptureOverflowError:
                LOGGER.debug(
                    "mic_capture_discontinuity rtp_timestamp=%d outcome=reset",
                    timestamp,
                )
                _offer_latest(raw_frames, _CaptureDiscontinuity(timestamp), "capture", timestamp)
                timestamp = (timestamp + 320) % (1 << 32)
                continue
            if frame is None:
                break
            _offer_latest(raw_frames, (frame, timestamp), "capture", timestamp, frame)
            timestamp = (timestamp + 320) % (1 << 32)
            await asyncio.sleep(0)
        await raw_frames.put(None)

    async def enhance_and_endpoint() -> None:
        last_timestamp: int | None = None
        expected_timestamp = start_timestamp
        while (item := await raw_frames.get()) is not None:
            discontinuity = isinstance(item, _CaptureDiscontinuity)
            current_timestamp = item.rtp_timestamp if discontinuity else item[1]
            if discontinuity or current_timestamp != expected_timestamp:
                reset = getattr(endpoint_processor, "reset_discontinuity", None)
                if callable(reset):
                    cast(Callable[[], None], reset)()
                if enhancer is not None:
                    enhancer.reset()
                if campp_streamer is not None:
                    campp_streamer.reset()
                LOGGER.debug(
                    "mic_pipeline_reset session=%s rtp_timestamp=%d outcome=discontinuity",
                    session_id, current_timestamp,
                )
                last_timestamp = None
            expected_timestamp = (current_timestamp + 320) % (1 << 32)
            if isinstance(item, _CaptureDiscontinuity):
                continue
            frame, timestamp = item
            last_timestamp = timestamp
            enhanced_frames = (
                (frame,)
                if enhancer is None
                else await enhancer.push_async(frame)
            )
            first_timestamp = timestamp - 320 * (len(enhanced_frames) - 1)
            for index, enhanced_frame in enumerate(enhanced_frames):
                timestamp = (first_timestamp + index * 320) % (1 << 32)
                analysis = _analyze(endpoint_processor, enhanced_frame, timestamp)
                if campp_streamer is not None:
                    for window in campp_streamer.push(enhanced_frame, timestamp, speech=analysis.speech):
                        _offer_latest(campp_windows, window, "campp", window.rtp_start_timestamp, window.pcm16le)
                if analysis.endpoint is not None:
                    _offer_latest(endpoints, analysis.endpoint, "asr", analysis.endpoint.rtp_start_timestamp, analysis.endpoint.pcm16le)

        if enhancer is not None and last_timestamp is not None:
            tail = await enhancer.flush_async()
            first_timestamp = last_timestamp - 320 * (len(tail) - 1)
            for index, enhanced_frame in enumerate(tail):
                timestamp = (first_timestamp + index * 320) % (1 << 32)
                analysis = _analyze(endpoint_processor, enhanced_frame, timestamp)
                if campp_streamer is not None:
                    for window in campp_streamer.push(enhanced_frame, timestamp, speech=analysis.speech):
                        _offer_latest(campp_windows, window, "campp", window.rtp_start_timestamp, window.pcm16le)
                if analysis.endpoint is not None:
                    _offer_latest(endpoints, analysis.endpoint, "asr", analysis.endpoint.rtp_start_timestamp, analysis.endpoint.pcm16le)
        endpoint = endpoint_processor.flush_enhanced_frames()
        if endpoint is not None:
            _offer_latest(endpoints, endpoint, "asr", endpoint.rtp_start_timestamp, endpoint.pcm16le)
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
        _ = await asyncio.gather(*tasks, return_exceptions=True)
        if enhancer is not None:
            await enhancer.aclose()


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
