"""NumPy port of the constrained 3D-Speaker ONNX Runtime FBank frontend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy

from mic.config import ConfigError


@dataclass(frozen=True, slots=True)
class CamppFbankConfig:
    sample_rate: int = 16_000
    frame_shift_ms: float = 10.0
    frame_length_ms: float = 25.0
    dither: float = 0.0
    num_bins: int = 80
    use_power: bool = True
    use_log_fbank: bool = True

    @property
    def frame_length(self) -> int:
        return int(self.sample_rate * self.frame_length_ms / 1_000)

    @property
    def frame_shift(self) -> int:
        return int(self.sample_rate * self.frame_shift_ms / 1_000)

    @classmethod
    def load(cls, path: Path) -> CamppFbankConfig:
        if not path.is_file():
            raise ConfigError(key="MIC_CAMPP_FBANK_CONFIG_PATH", reason="file does not exist")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            frame = value["FrameExtractionOptions"]
            mel = value["MelBanksOptions"]
            config = cls(
                sample_rate=int(frame["sample_freq"]),
                frame_shift_ms=float(frame["frame_shift_ms"]),
                frame_length_ms=float(frame["frame_length_ms"]),
                dither=float(frame.get("dither", 0.0)),
                num_bins=int(mel["num_bins"]),
                use_power=bool(value.get("use_power", True)),
                use_log_fbank=bool(value.get("use_log_fbank", True)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConfigError(
                key="MIC_CAMPP_FBANK_CONFIG_PATH", reason="invalid 3D-Speaker FBank JSON"
            ) from exc
        if config != cls():
            raise ConfigError(
                key="MIC_CAMPP_FBANK_CONFIG_PATH",
                reason="must use 16kHz/25ms/10ms/80-bin/dither-0 power log FBank",
            )
        return config


class CamppFbank:
    """Feature extractor equivalent to the constrained official Runtime settings."""

    def __init__(self, config: CamppFbankConfig) -> None:
        self._config = config
        indices = numpy.arange(config.frame_length, dtype=numpy.float32)
        self._window = (
            0.5 - 0.5 * numpy.cos(2 * numpy.pi * indices / (config.frame_length - 1))
        ) ** 0.85
        self._filters = _mel_filters(config)

    def extract(self, pcm16le: bytes) -> numpy.ndarray:
        samples = numpy.frombuffer(pcm16le, dtype="<i2").astype(numpy.float32) / 32768
        length = self._config.frame_length
        shift = self._config.frame_shift
        if samples.size < length:
            return numpy.empty((0, self._config.num_bins), dtype=numpy.float32)
        count = 1 + (samples.size - length) // shift
        frames = numpy.stack(
            [samples[index * shift : index * shift + length] for index in range(count)]
        )
        frames -= frames.mean(axis=1, keepdims=True)
        frames[:, 1:] -= 0.97 * frames[:, :-1]
        frames[:, 0] -= 0.97 * frames[:, 0]
        frames *= self._window
        spectrum = numpy.fft.rfft(frames, n=512, axis=1)[:, :-1]
        power = (spectrum.real**2 + spectrum.imag**2).astype(numpy.float32)
        features = power @ self._filters.T
        features = numpy.log(numpy.maximum(features, numpy.finfo(numpy.float32).eps))
        return (features - features.mean(axis=0, keepdims=True)).astype(numpy.float32)


def _mel_filters(config: CamppFbankConfig) -> numpy.ndarray:
    def hz_to_mel(value: float) -> float:
        return float(1127.0 * numpy.log(1.0 + value / 700.0))

    frequencies = numpy.arange(256, dtype=numpy.float32) * (config.sample_rate / 512)
    mel_frequencies = 1127.0 * numpy.log(1.0 + frequencies / 700.0)
    points = numpy.linspace(
        hz_to_mel(20.0), hz_to_mel(config.sample_rate / 2), config.num_bins + 2
    )
    filters = numpy.zeros((config.num_bins, frequencies.size), dtype=numpy.float32)
    for index in range(config.num_bins):
        left, center, right = points[index : index + 3]
        filters[index] = numpy.maximum(
            0.0,
            numpy.minimum(
                (mel_frequencies - left) / (center - left),
                (right - mel_frequencies) / (right - center),
            ),
        )
    return filters
