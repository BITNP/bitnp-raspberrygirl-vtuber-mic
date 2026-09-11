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
from mic.portaudio_capture import CaptureOverflowError
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


def test_capture_overflow_advances_time_and_resets_streaming_state() -> None:
    class OverflowCapture:
        def __init__(self) -> None:
            self.calls = 0

        async def read_block(self) -> bytes | None:
            self.calls += 1
            if self.calls == 1:
                raise CaptureOverflowError
            if self.calls == 2:
                return b"\x00" * 640
            return None

    class Processor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.resets = 0

        def reset_discontinuity(self) -> None:
            self.resets += 1

    processor = Processor()

    asyncio.run(
        run_continuous_pipeline(
            OverflowCapture(), processor, start_timestamp=0xFFFF_FF00
        )
    )

    assert processor.resets == 1
    assert processor.received == [(b"\x00" * 640, 0x40)]


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
            self.evidence_ready = asyncio.Event()

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
            self.evidence_ready.set()

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
        await asyncio.wait_for(processor.evidence_ready.wait(), timeout=1)
        assert [(item.rtp_start_timestamp, item.rtp_end_timestamp) for item in processor.evidence] == [
            (0, 24_000)
        ]
        processor.release_asr.set()
        await task

    asyncio.run(scenario())


def test_full_asr_queue_does_not_stop_vad_or_capture() -> None:
    class Processor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        def analyze_enhanced_frame(self, frame: bytes, timestamp: int) -> FrameAnalysis:
            self.received.append((frame, timestamp))
            return FrameAnalysis(True, AsrEndpoint(frame, timestamp, timestamp + 320))

        async def recognize_endpoint(self, endpoint: AsrEndpoint) -> None:
            self.started.set()
            await self.release.wait()
            self.recognized.append(endpoint)

        def flush_enhanced_frames(self) -> None:
            return None

    class Capture:
        count = 0
        done = asyncio.Event()

        async def read_block(self) -> bytes | None:
            await asyncio.sleep(0)
            if self.count == 300:
                self.done.set()
                return None
            self.count += 1
            return bytes(640)

    async def scenario() -> None:
        capture, processor = Capture(), Processor()
        task = asyncio.create_task(run_continuous_pipeline(capture, processor, start_timestamp=0))
        try:
            await processor.started.wait()
            await asyncio.wait_for(capture.done.wait(), timeout=1)
            assert len(processor.received) == 300
        finally:
            processor.release.set()
            await task
        assert len(processor.recognized) <= 3
        assert processor.recognized[-1].rtp_start_timestamp == 299 * 320

    asyncio.run(scenario())


def test_slow_campp_does_not_block_capture_and_retains_latest_windows() -> None:
    class Model:
        revision = "test"

        def embed_pcm16le(self, _pcm: bytes) -> CamPlusPlusEmbedding:
            return CamPlusPlusEmbedding((1.0, 0.0))

    class Processor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()
            self.evidence: list[CamPlusPlusWindow] = []

        def analyze_enhanced_frame(self, frame: bytes, timestamp: int) -> FrameAnalysis:
            self.received.append((frame, timestamp))
            return FrameAnalysis(True, None)

        async def emit_voice_evidence(self, window, embedding, revision) -> None:
            self.started.set()
            await self.release.wait()
            self.evidence.append(window)

    class Capture:
        count = 0
        done = asyncio.Event()

        async def read_block(self) -> bytes | None:
            await asyncio.sleep(0)
            if self.count == 1000:
                self.done.set()
                return None
            self.count += 1
            return bytes(640)

    async def scenario() -> None:
        capture, processor = Capture(), Processor()
        task = asyncio.create_task(run_continuous_pipeline(
            capture, processor, start_timestamp=0,
            campp_streamer=CamPlusPlusStreamingProcessor(), campp_model=Model(),
        ))
        try:
            await asyncio.wait_for(processor.started.wait(), timeout=1)
            await asyncio.wait_for(capture.done.wait(), timeout=1)
            assert len(processor.received) == 1000
        finally:
            processor.release.set()
            await task
        assert len(processor.evidence) <= 3
        assert processor.evidence[-1].rtp_end_timestamp > 300000

    asyncio.run(scenario())


def test_capture_queue_overload_resets_state_before_retained_audio() -> None:
    import threading

    class SlowModel:
        started = threading.Event()
        release = threading.Event()

        def enhance(self, pcm: bytes) -> bytes:
            self.started.set()
            self.release.wait()
            return pcm

    class Processor(_Processor):
        def __init__(self) -> None:
            super().__init__()
            self.resets = 0

        def reset_discontinuity(self) -> None:
            self.resets += 1

    class Capture:
        count = 0
        done = asyncio.Event()

        async def read_block(self) -> bytes | None:
            await asyncio.sleep(0)
            if self.count == 300:
                self.done.set()
                return None
            self.count += 1
            return bytes(640)

    async def scenario() -> None:
        model, processor, capture = SlowModel(), Processor(), Capture()
        enhancer = ZipEnhancerStreamingProcessor(model, window_ms=20)
        task = asyncio.create_task(run_continuous_pipeline(capture, processor, start_timestamp=0, enhancer=enhancer))
        try:
            await asyncio.wait_for(capture.done.wait(), timeout=1)
        finally:
            model.release.set()
            await task
        assert processor.resets > 0
        assert processor.received[-1][1] == 299 * 320
        assert len(processor.received) < 300

    asyncio.run(scenario())
