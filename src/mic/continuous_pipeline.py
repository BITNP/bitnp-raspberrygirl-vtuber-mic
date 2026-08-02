"""Bounded continuous capture, enhancement, VAD and recognition pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Final, Protocol

from mic.asr import AsrEndpoint
from mic.speech_models import ZipEnhancerStreamingProcessor

RAW_QUEUE_MAX_FRAMES: Final = 75
ENDPOINT_QUEUE_MAX_SEGMENTS: Final = 2


class BlockCapture(Protocol):
    async def read_block(self) -> bytes | None: ...


class EndpointProcessor(Protocol):
    def push_enhanced_frame(
        self, frame: bytes, rtp_timestamp: int
    ) -> AsrEndpoint | None: ...

    def flush_enhanced_frames(self) -> AsrEndpoint | None: ...

    async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None: ...


type TimestampedFrame = tuple[bytes, int]


async def run_continuous_pipeline(
    capture: BlockCapture,
    endpoint_processor: EndpointProcessor,
    *,
    start_timestamp: int,
    enhancer: ZipEnhancerStreamingProcessor | None = None,
) -> None:
    """Keep capture active while serial workers enhance, endpoint and recognize audio."""
    raw_frames: asyncio.Queue[TimestampedFrame | None] = asyncio.Queue(
        maxsize=RAW_QUEUE_MAX_FRAMES
    )
    endpoints: asyncio.Queue[AsrEndpoint | None] = asyncio.Queue(
        maxsize=ENDPOINT_QUEUE_MAX_SEGMENTS
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
                endpoint = endpoint_processor.push_enhanced_frame(
                    enhanced_frame, (first_timestamp + index * 320) % (1 << 32)
                )
                if endpoint is not None:
                    await endpoints.put(endpoint)

        if enhancer is not None and last_timestamp is not None:
            tail = await asyncio.to_thread(enhancer.flush)
            first_timestamp = last_timestamp - 320 * (len(tail) - 1)
            for index, enhanced_frame in enumerate(tail):
                endpoint = endpoint_processor.push_enhanced_frame(
                    enhanced_frame, (first_timestamp + index * 320) % (1 << 32)
                )
                if endpoint is not None:
                    await endpoints.put(endpoint)
        endpoint = endpoint_processor.flush_enhanced_frames()
        if endpoint is not None:
            await endpoints.put(endpoint)
        await endpoints.put(None)

    async def recognize() -> None:
        while (endpoint := await endpoints.get()) is not None:
            await endpoint_processor.recognize_endpoint(endpoint)

    tasks = [
        asyncio.create_task(capture_frames()),
        asyncio.create_task(enhance_and_endpoint()),
        asyncio.create_task(recognize()),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
