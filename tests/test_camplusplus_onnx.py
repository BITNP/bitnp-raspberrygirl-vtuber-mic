import json
from pathlib import Path

import numpy
import pytest

from mic.camplusplus import CamPlusPlusOnnx
from mic.config import ConfigError


class _Item:
    def __init__(self, name: str, shape: list[int | str], item_type: str = "tensor(float)") -> None:
        self.name = name
        self.shape = shape
        self.type = item_type


class _Session:
    def __init__(self, output_shape: list[int | str] | None = None) -> None:
        self.calls: list[dict[str, numpy.ndarray]] = []
        self._output_shape = output_shape or [1, 192]

    def get_inputs(self) -> list[_Item]:
        return [_Item("feature", [1, "frames", 80])]

    def get_outputs(self) -> list[_Item]:
        return [_Item("embedding", self._output_shape)]

    def run(self, _outputs: object, values: dict[str, numpy.ndarray]) -> list[numpy.ndarray]:
        self.calls.append(values)
        return [numpy.ones((1, 192), dtype=numpy.float32)]


def _fbank_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "FrameExtractionOptions": {
                    "sample_freq": 16000,
                    "frame_shift_ms": 10.0,
                    "frame_length_ms": 25.0,
                    "dither": 0.0,
                },
                "MelBanksOptions": {"num_bins": 80},
                "use_power": True,
                "use_log_fbank": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_camplusplus_requires_official_feature_contract(monkeypatch, tmp_path: Path) -> None:
    session = _Session()
    monkeypatch.setattr("mic.camplusplus.onnxruntime.InferenceSession", lambda *_args, **_kwargs: session)
    model_path = tmp_path / "campplus.onnx"
    model_path.touch()
    adapter = CamPlusPlusOnnx(model_path, "campplus-v1", _fbank_config(tmp_path / "fbank.json"))

    embedding = adapter.embed_pcm16le((numpy.arange(24_000) % 500).astype("<i2").tobytes())

    assert len(embedding.values) == 192
    assert numpy.isclose(numpy.linalg.norm(embedding.values), 1.0)
    assert session.calls[0]["feature"].shape == (1, 148, 80)


def test_camplusplus_rejects_nonofficial_embedding_dimensions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "mic.camplusplus.onnxruntime.InferenceSession",
        lambda *_args, **_kwargs: _Session([1, 256]),
    )
    model_path = tmp_path / "campplus.onnx"
    model_path.touch()

    with pytest.raises(ConfigError, match="embedding"):
        CamPlusPlusOnnx(model_path, "campplus-v1", _fbank_config(tmp_path / "fbank.json"))
