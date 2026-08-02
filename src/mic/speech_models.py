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
    """Official two-input ZipEnhancer ONNX adapter, executed on CPU only."""

    def __init__(self, model_path: Path) -> None:
        self._session = _session(model_path, "MIC_ZIPENHANCER_MODEL_PATH")
        inputs = self._session.get_inputs()
        if len(inputs) != 2 or {item.name for item in inputs} != {"noisy_mag", "noisy_pha"}:
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH",
                reason="must be official ZipEnhancer noisy_mag/noisy_pha ONNX",
            )
        self._inputs = {item.name: item for item in inputs}

    def enhance(self, pcm16le: bytes) -> bytes:
        if len(pcm16le) % 2:
            raise ConfigError(key="capture.block", reason="must contain PCM16 samples")
        samples = numpy.frombuffer(pcm16le, dtype="<i2").astype(numpy.float32) / 32768
        if samples.size == 0:
            return pcm16le
        norm = numpy.sqrt(samples.size / max(float(numpy.sum(samples**2)), 1e-12))
        magnitude, phase, padded = _mag_pha_stft(samples * norm)
        outputs = self._session.run(
            None,
            {"noisy_mag": magnitude[numpy.newaxis], "noisy_pha": phase[numpy.newaxis]},
        )
        if len(outputs) < 2:
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH", reason="model must return amp_g and pha_g"
            )
        amp_g, pha_g = (numpy.asarray(output) for output in outputs[:2])
        expected = (1, _N_FFT // 2 + 1, magnitude.shape[1])
        if amp_g.shape != expected or pha_g.shape != expected:
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH",
                reason="model output does not match ZipEnhancer spectrogram shape",
            )
        enhanced = _mag_pha_istft(amp_g[0], pha_g[0], padded)
        enhanced = enhanced[: samples.size] / norm
        return numpy.clip(enhanced * 32768, -32768, 32767).astype("<i2").tobytes()


_N_FFT = 400
_HOP = 100
_COMPRESS = 0.3


def _mag_pha_stft(samples: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, int]:
    padded = samples.size + _N_FFT
    signal = numpy.pad(samples, (_N_FFT // 2, _N_FFT // 2), mode="reflect")
    window = numpy.hanning(_N_FFT + 1)[:-1].astype(numpy.float32)
    count = 1 + (signal.size - _N_FFT) // _HOP
    frames = numpy.stack([signal[index * _HOP : index * _HOP + _N_FFT] * window for index in range(count)])
    spectrum = numpy.fft.rfft(frames, axis=1).T
    return numpy.abs(spectrum).astype(numpy.float32) ** _COMPRESS, numpy.angle(spectrum).astype(numpy.float32), padded


def _mag_pha_istft(magnitude: numpy.ndarray, phase: numpy.ndarray, padded: int) -> numpy.ndarray:
    window = numpy.hanning(_N_FFT + 1)[:-1].astype(numpy.float32)
    frames = numpy.fft.irfft((magnitude ** (1 / _COMPRESS)) * numpy.exp(1j * phase), n=_N_FFT, axis=0).T
    signal = numpy.zeros((frames.shape[0] - 1) * _HOP + _N_FFT, dtype=numpy.float32)
    weights = numpy.zeros_like(signal)
    for index, frame in enumerate(frames):
        offset = index * _HOP
        signal[offset : offset + _N_FFT] += frame * window
        weights[offset : offset + _N_FFT] += window**2
    signal /= numpy.maximum(weights, 1e-8)
    return signal[_N_FFT // 2 : _N_FFT // 2 + padded - _N_FFT]


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
