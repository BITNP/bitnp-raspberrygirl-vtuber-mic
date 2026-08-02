"""Local ONNX speech enhancement and VAD adapters for Mic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy
import onnxruntime

from mic.config import ConfigError

SAMPLE_RATE_HZ = 16_000


def _session(path: Path, key: str) -> onnxruntime.InferenceSession:
    if not path.is_file():
        raise ConfigError(key=key, reason="model file does not exist")
    return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])


class ZipEnhancerOnnx:
    """Full local ZipEnhancer ONNX waveform model, executed on CPU only.

    Export the controlled ZipEnhancer model with one waveform input and one
    enhanced-waveform output.  Frames are buffered by the model's caller, so
    no raw audio is persisted.
    """

    def __init__(self, model_path: Path) -> None:
        self._session = _session(model_path, "MIC_ZIPENHANCER_MODEL_PATH")
        inputs = self._session.get_inputs()
        if len(inputs) != 1:
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH", reason="model must have one waveform input"
            )
        self._input = inputs[0]

    def enhance(self, pcm16le: bytes) -> bytes:
        samples = numpy.frombuffer(pcm16le, dtype="<i2").astype(numpy.float32) / 32768
        if len(self._input.shape) == 3:
            waveform = samples[numpy.newaxis, numpy.newaxis, :]
        else:
            waveform = samples[numpy.newaxis, :]
        output = numpy.asarray(self._session.run(None, {self._input.name: waveform})[0])
        enhanced = output.reshape(-1)
        if enhanced.size != samples.size:
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH", reason="output waveform length differs"
            )
        return numpy.clip(enhanced * 32768, -32768, 32767).astype("<i2").tobytes()


@dataclass(slots=True)
class SileroVadOnnx:
    """Stateful Silero VAD ONNX adapter for 16 kHz 512-sample windows."""

    _session: onnxruntime.InferenceSession
    _input_name: str
    _state_name: str
    _sample_rate_name: str
    _state: numpy.ndarray

    @classmethod
    def load(cls, model_path: Path) -> SileroVadOnnx:
        session = _session(model_path, "MIC_VAD_MODEL_PATH")
        names = {item.name for item in session.get_inputs()}
        if not {"input", "state", "sr"}.issubset(names):
            raise ConfigError(key="MIC_VAD_MODEL_PATH", reason="must be a Silero VAD ONNX model")
        return cls(
            session,
            "input",
            "state",
            "sr",
            numpy.zeros((2, 1, 128), dtype=numpy.float32),
        )

    def speech_probability(self, pcm16le: bytes) -> float:
        samples = numpy.frombuffer(pcm16le, dtype="<i2").astype(numpy.float32) / 32768
        if samples.size != 512:
            raise ConfigError(key="MIC_VAD_MODEL_PATH", reason="requires 512 samples")
        output, state = self._session.run(
            None,
            {self._input_name: samples[numpy.newaxis, :], self._state_name: self._state, self._sample_rate_name: numpy.array(SAMPLE_RATE_HZ, dtype=numpy.int64)},
        )
        self._state = numpy.asarray(state)
        return float(numpy.asarray(output).reshape(-1)[0])
