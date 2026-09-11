"""Official 3D-Speaker CAM++ ONNX embedding boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy

from mic.campp_fbank import CamppFbank, CamppFbankConfig
from mic.config import ConfigError
from mic.onnx_session import create_session

_EMBEDDING_DIMENSIONS = frozenset({192, 512})
_FRAME_SAMPLES = 320
_WINDOW_SAMPLES = 24_000
_STEP_SAMPLES = 12_000
_TRAILING_SILENCE_FRAMES = 20


@dataclass(frozen=True, slots=True)
class CamPlusPlusEmbedding:
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CamPlusPlusWindow:
    pcm16le: bytes
    rtp_start_timestamp: int
    rtp_end_timestamp: int
    speech_ms: int


class CamPlusPlusStreamingProcessor:
    """Builds official 1.5 s CAM++ windows every 0.75 s from VAD decisions."""

    def __init__(self) -> None:
        self._pcm = bytearray()
        self._speech_samples: list[bool] = []
        self._start_timestamp: int | None = None
        self._silence_frames = 0

    def push(
        self, frame: bytes, rtp_timestamp: int, *, speech: bool
    ) -> tuple[CamPlusPlusWindow, ...]:
        if len(frame) != _FRAME_SAMPLES * 2:
            raise ConfigError(key="capture.block", reason="must contain exactly 640 PCM16 bytes")
        if self._start_timestamp is None:
            if not speech:
                return ()
            self._start_timestamp = rtp_timestamp
        self._pcm.extend(frame)
        self._speech_samples.extend([speech] * _FRAME_SAMPLES)
        self._silence_frames = 0 if speech else self._silence_frames + 1
        windows = self._ready_windows()
        if self._silence_frames >= _TRAILING_SILENCE_FRAMES:
            self.reset()
        return windows

    def reset(self) -> None:
        self._pcm.clear()
        self._speech_samples.clear()
        self._start_timestamp = None
        self._silence_frames = 0

    def _ready_windows(self) -> tuple[CamPlusPlusWindow, ...]:
        windows: list[CamPlusPlusWindow] = []
        while len(self._speech_samples) >= _WINDOW_SAMPLES:
            start = self._start_timestamp
            if start is None:
                break
            speech_samples = sum(self._speech_samples[:_WINDOW_SAMPLES])
            speech_ms = speech_samples * 1_000 // 16_000
            if speech_ms >= 1_000:
                windows.append(
                    CamPlusPlusWindow(
                        bytes(self._pcm[: _WINDOW_SAMPLES * 2]),
                        start,
                        (start + _WINDOW_SAMPLES) % (1 << 32),
                        speech_ms,
                    )
                )
            del self._pcm[: _STEP_SAMPLES * 2]
            del self._speech_samples[:_STEP_SAMPLES]
            self._start_timestamp = (start + _STEP_SAMPLES) % (1 << 32)
        return tuple(windows)


class CamPlusPlusOnnx:
    """Runs a controlled CAM++ ``feature -> embedding`` ONNX model with GPU preference."""

    def __init__(self, model_path: Path, revision: str, fbank_config_path: Path) -> None:
        if not model_path.is_file() or not revision.strip():
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="model and revision required")
        self.revision = revision.strip()
        self._fbank = CamppFbank(CamppFbankConfig.load(fbank_config_path))
        self._session = create_session(model_path)
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or inputs[0].name != "feature" or len(inputs[0].shape) != 3:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="must have [batch, frames, 80] feature input")
        if inputs[0].shape[-1] != 80 or inputs[0].type != "tensor(float)":
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="feature input must be float32 with 80 bins")
        if isinstance(inputs[0].shape[1], int):
            raise ConfigError(
                key="MIC_CAMPP_MODEL_PATH", reason="feature input must have a dynamic frame axis"
            )
        if len(outputs) != 1 or outputs[0].name != "embedding" or len(outputs[0].shape) != 2:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="must have [batch, dimensions] embedding output")
        if outputs[0].shape[-1] not in _EMBEDDING_DIMENSIONS or outputs[0].type != "tensor(float)":
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="unsupported float32 embedding dimensions")
        self._input_name = inputs[0].name

    def embed_pcm16le(self, pcm16le: bytes) -> CamPlusPlusEmbedding:
        features = self._fbank.extract(pcm16le)
        if not features.size:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="insufficient samples for FBank")
        raw_output = numpy.asarray(
            self._session.run(None, {self._input_name: features[numpy.newaxis, :, :]})[0]
        )
        if raw_output.shape not in {(1, 192), (1, 512)}:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="invalid embedding output shape")
        output = raw_output.reshape(-1).astype(numpy.float64)
        norm = float(numpy.linalg.norm(output))
        if output.size not in _EMBEDDING_DIMENSIONS or not numpy.isfinite(output).all() or norm == 0:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="invalid embedding output")
        output /= norm
        return CamPlusPlusEmbedding(tuple(float(value) for value in output))
