from pathlib import Path

import numpy
import pytest

from mic.config import ConfigError
from mic.speech_models import (
    SileroVadOnnx,
    ZipEnhancerOnnx,
    ZipEnhancerStreamingProcessor,
)


class _Item:
    def __init__(self, name: str) -> None:
        self.name = name


class _ZipSession:
    def __init__(self, input_names: tuple[str, ...] = ("noisy_mag", "noisy_pha")) -> None:
        self._inputs = [_Item(name) for name in input_names]
        self.calls: list[dict[str, numpy.ndarray]] = []

    def get_inputs(self) -> list[_Item]:
        return self._inputs

    def run(self, _outputs: object, inputs: dict[str, numpy.ndarray]) -> list[numpy.ndarray]:
        self.calls.append(inputs)
        return [inputs["noisy_mag"], inputs["noisy_pha"]]


def test_zipenhancer_uses_official_spectrogram_contract(monkeypatch) -> None:
    session = _ZipSession()
    monkeypatch.setattr("mic.speech_models._session", lambda *_: session)
    adapter = ZipEnhancerOnnx(Path("/controlled/zipenhancer.onnx"))
    source = (numpy.arange(640, dtype=numpy.int16) - 320).astype("<i2").tobytes()

    enhanced = adapter.enhance(source)

    assert len(enhanced) == len(source)
    assert session.calls[0]["noisy_mag"].shape == (1, 201, 7)
    assert session.calls[0]["noisy_pha"].shape == (1, 201, 7)
    assert numpy.max(
        numpy.abs(
            numpy.frombuffer(enhanced, dtype="<i2").astype(numpy.int32)
            - numpy.frombuffer(source, dtype="<i2").astype(numpy.int32)
        )
    ) <= 1


def test_zipenhancer_rejects_nonofficial_model_inputs(monkeypatch) -> None:
    monkeypatch.setattr(
        "mic.speech_models._session", lambda *_: _ZipSession(("audio", "state"))
    )

    with pytest.raises(ConfigError, match="noisy_mag/noisy_pha"):
        ZipEnhancerOnnx(Path("/controlled/other.onnx"))


def test_zipenhancer_streaming_processor_emits_complete_windows_and_tail() -> None:
    class Enhancer:
        def __init__(self) -> None:
            self.inputs: list[bytes] = []

        def enhance(self, pcm16le: bytes) -> bytes:
            self.inputs.append(pcm16le)
            return pcm16le

    enhancer = Enhancer()
    processor = ZipEnhancerStreamingProcessor(enhancer, window_ms=40)  # type: ignore[arg-type]
    first = bytes(640)
    second = bytes(639) + b"\x01"
    third = bytes(639) + b"\x02"

    assert processor.push(first) == ()
    assert processor.push(second) == (first, second)
    assert processor.push(third) == ()
    assert processor.flush() == (third,)
    assert enhancer.inputs == [first + second, third]


def test_zipenhancer_streaming_processor_fails_open_for_one_window(caplog) -> None:
    class FailingEnhancer:
        def enhance(self, pcm16le: bytes) -> bytes:
            _ = pcm16le
            raise RuntimeError("inference failed")

    processor = ZipEnhancerStreamingProcessor(FailingEnhancer(), window_ms=20)  # type: ignore[arg-type]
    source = bytes(640)

    assert processor.push(source) == (source,)
    assert "forwarding raw PCM" in caplog.text


def test_silero_vad_sends_state_and_updates_it() -> None:
    class Session:
        def __init__(self) -> None:
            self.inputs: dict[str, numpy.ndarray] | None = None

        def run(
            self, _outputs: object, inputs: dict[str, numpy.ndarray]
        ) -> list[numpy.ndarray]:
            self.inputs = inputs
            return [numpy.array([[0.75]], dtype=numpy.float32), numpy.ones((2, 1, 128))]

    session = Session()
    vad = SileroVadOnnx(
        session,  # pyright: ignore[reportArgumentType]
        "input",
        "state",
        "sr",
        numpy.zeros((2, 1, 128), dtype=numpy.float32),
        numpy.zeros((1, 64), dtype=numpy.float32),
    )

    probability = vad.speech_probability(bytes(1_024))

    assert probability == 0.75
    assert session.inputs is not None
    assert session.inputs["input"].shape == (1, 576)
    assert numpy.all(session.inputs["input"][:, :64] == 0)
    assert session.inputs["state"].shape == (2, 1, 128)
    assert session.inputs["sr"].item() == 16_000
    assert numpy.all(vad._state == 1)


def test_silero_vad_carries_the_previous_window_tail_as_context() -> None:
    class Session:
        def __init__(self) -> None:
            self.inputs: list[dict[str, numpy.ndarray]] = []

        def run(
            self, _outputs: object, inputs: dict[str, numpy.ndarray]
        ) -> list[numpy.ndarray]:
            self.inputs.append({name: value.copy() for name, value in inputs.items()})
            return [numpy.array([[0.75]], dtype=numpy.float32), numpy.ones((2, 1, 128))]

    first_window = numpy.arange(512, dtype="<i2")
    session = Session()
    vad = SileroVadOnnx(
        session,  # pyright: ignore[reportArgumentType]
        "input",
        "state",
        "sr",
        numpy.zeros((2, 1, 128), dtype=numpy.float32),
        numpy.zeros((1, 64), dtype=numpy.float32),
    )

    _ = vad.speech_probability(first_window.tobytes())
    _ = vad.speech_probability(bytes(1_024))

    assert numpy.allclose(
        session.inputs[1]["input"][0, :64], first_window[-64:] / 32768
    )


def test_slow_enhancement_falls_back_without_accumulating_inference() -> None:
    import asyncio
    import threading

    class SlowEnhancer:
        calls = 0
        started = threading.Event()
        release = threading.Event()

        def enhance(self, pcm: bytes) -> bytes:
            self.calls += 1
            self.started.set()
            self.release.wait()
            return bytes([99]) * len(pcm)

    async def scenario() -> None:
        model = SlowEnhancer()
        processor = ZipEnhancerStreamingProcessor(model, window_ms=20)
        frame = bytes([1]) * 640
        try:
            assert await processor.push_async(frame) == (frame,)
            assert model.started.is_set()
            for _ in range(10):
                assert await processor.push_async(frame) == (frame,)
            assert model.calls == 1
            model.release.set()
            await processor.aclose()
        finally:
            model.release.set()

    asyncio.run(scenario())


def test_late_enhancement_never_replaces_a_new_window() -> None:
    import asyncio
    import threading

    class Model:
        calls = 0
        release = threading.Event()

        def enhance(self, pcm: bytes) -> bytes:
            self.calls += 1
            if self.calls == 1:
                self.release.wait()
                return bytes([99]) * len(pcm)
            return pcm

    async def scenario() -> None:
        model = Model()
        processor = ZipEnhancerStreamingProcessor(model, window_ms=20)
        try:
            first, second = bytes([1]) * 640, bytes([2]) * 640
            assert await processor.push_async(first) == (first,)
            processor.reset()
            model.release.set()
            assert processor._inference is not None
            await asyncio.shield(processor._inference)
            assert await processor.push_async(second) == (second,)
        finally:
            model.release.set()
            await processor.aclose()

    asyncio.run(scenario())
