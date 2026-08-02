import asyncio
from dataclasses import dataclass, field

from mic.asr import AsrEndpoint
from mic.continuous_pipeline import run_continuous_pipeline
from mic.speech_models import ZipEnhancerStreamingProcessor


@dataclass
class _Capture:
    frames: list[bytes | None]

    async def read_block(self) -> bytes | None:
        return self.frames.pop(0)


@dataclass
class _Processor:
    received: list[tuple[bytes, int]] = field(default_factory=list)
    recognized: list[AsrEndpoint] = field(default_factory=list)

    def push_enhanced_frame(
        self, frame: bytes, rtp_timestamp: int
    ) -> AsrEndpoint | None:
        self.received.append((frame, rtp_timestamp))
        return None

    def flush_enhanced_frames(self) -> AsrEndpoint | None:
        return AsrEndpoint(b"\x00" * 640, 0, 320)

    async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None:
        self.recognized.append(endpoint)


def test_pipeline_preserves_enhanced_frame_order_timestamps_and_tail() -> None:
    class MarkingEnhancer:
        def enhance(self, pcm16le: bytes) -> bytes:
            return bytes(value ^ 0xFF for value in pcm16le)

    frames = [bytes([value]) * 640 for value in (1, 2, 3)]
    capture = _Capture([*frames, None])
    processor = _Processor()
    enhancer = ZipEnhancerStreamingProcessor(MarkingEnhancer(), window_ms=40)  # type: ignore[arg-type]

    asyncio.run(
        run_continuous_pipeline(
            capture, processor, start_timestamp=960, enhancer=enhancer  # type: ignore[arg-type]
        )
    )

    assert processor.received == [
        (bytes([0xFE]) * 640, 960),
        (bytes([0xFD]) * 640, 1_280),
        (bytes([0xFC]) * 640, 1_600),
    ]
    assert len(processor.recognized) == 1
