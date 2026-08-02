from pathlib import Path

import numpy
import pytest

from mic.config import ConfigError
from mic.speech_models import SileroVadOnnx, ZipEnhancerOnnx


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
        session, "input", "state", "sr", numpy.zeros((2, 1, 128), dtype=numpy.float32)
    )

    probability = vad.speech_probability(bytes(1_024))

    assert probability == 0.75
    assert session.inputs is not None
    assert session.inputs["input"].shape == (1, 512)
    assert session.inputs["state"].shape == (2, 1, 128)
    assert session.inputs["sr"].item() == 16_000
    assert numpy.all(vad._state == 1)
