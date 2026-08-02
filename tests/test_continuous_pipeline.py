import asyncio
from dataclasses import dataclass, field

from mic.asr import AsrEndpoint
from mic.asr_runtime import FrameAnalysis
from mic.camplusplus import (
    CamPlusPlusEmbedding,
    CamPlusPlusStreamingProcessor,
    CamPlusPlusWindow,
)
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

    def analyze_enhanced_frame(self, frame: bytes, rtp_timestamp: int) -> FrameAnalysis:
        return FrameAnalysis(False, self.push_enhanced_frame(frame, rtp_timestamp))

    def flush_enhanced_frames(self) -> AsrEndpoint | None:
        return AsrEndpoint(b"\x00" * 640, 0, 320)

    async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None:
        self.recognized.append(endpoint)

    async def emit_voice_evidence(
        self, window: CamPlusPlusWindow, embedding: CamPlusPlusEmbedding, revision: str
    ) -> None:
        _ = window, embedding, revision


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


def test_camplusplus_worker_emits_evidence_while_asr_is_blocked() -> None:
    class Model:
        revision = "campplus-test-v1"

        def embed_pcm16le(self, pcm16le: bytes) -> CamPlusPlusEmbedding:
            assert len(pcm16le) == 48_000
            return CamPlusPlusEmbedding((1.0, 0.0))

    class Processor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.asr_started = asyncio.Event()
            self.release_asr = asyncio.Event()
            self.evidence: list[CamPlusPlusWindow] = []

        def analyze_enhanced_frame(self, frame: bytes, rtp_timestamp: int) -> FrameAnalysis:
            endpoint = AsrEndpoint(frame, rtp_timestamp, rtp_timestamp + 320) if not self.received else None
            self.received.append((frame, rtp_timestamp))
            return FrameAnalysis(True, endpoint)

        async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None:
            self.asr_started.set()
            await self.release_asr.wait()
            self.recognized.append(endpoint)

        async def emit_voice_evidence(
            self, window: CamPlusPlusWindow, embedding: CamPlusPlusEmbedding, revision: str
        ) -> None:
            assert embedding.values == (1.0, 0.0)
            assert revision == "campplus-test-v1"
            self.evidence.append(window)

    async def scenario() -> None:
        processor = Processor()
        capture = _Capture([b"\x01\x00" * 320] * 75 + [None])
        task = asyncio.create_task(
            run_continuous_pipeline(
                capture,
                processor,
                start_timestamp=0,
                campp_streamer=CamPlusPlusStreamingProcessor(),
                campp_model=Model(),
            )
        )
        await processor.asr_started.wait()
        for _ in range(20):
            if processor.evidence:
                break
            await asyncio.sleep(0)
        assert [(item.rtp_start_timestamp, item.rtp_end_timestamp) for item in processor.evidence] == [
            (0, 24_000)
        ]
        processor.release_asr.set()
        await task

    asyncio.run(scenario())
