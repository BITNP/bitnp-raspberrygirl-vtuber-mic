"""Local ONNX speech enhancement and VAD adapters for Mic."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy
import onnxruntime

from mic.config import ConfigError

SAMPLE_RATE_HZ = 16_000

PCM16_20MS_FRAME_BYTES = 640

SILERO_VAD_WINDOW_SAMPLES = 512

SILERO_VAD_CONTEXT_SAMPLES = 64

LOGGER = logging.getLogger(__name__)


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
        if not numpy.isfinite(amp_g).all() or not numpy.isfinite(pha_g).all():
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH", reason="model output is not finite"
            )
        enhanced = _mag_pha_istft(amp_g[0], pha_g[0], padded)
        enhanced = enhanced[: samples.size] / norm
        output = numpy.clip(enhanced * 32768, -32768, 32767).astype("<i2").tobytes()
        if len(output) != len(pcm16le):
            raise ConfigError(
                key="MIC_ZIPENHANCER_MODEL_PATH", reason="model output length changed"
            )
        return output


class PcmEnhancer(Protocol):
    def enhance(self, pcm16le: bytes) -> bytes: ...


class ZipEnhancerStreamingProcessor:
    """Accumulates fixed PCM windows and fail-opens if one inference fails."""

    def __init__(
        self, enhancer: PcmEnhancer, *, window_ms: int = 500, session_id: str = ""
    ) -> None:
        if window_ms < 20 or window_ms % 20:
            raise ValueError("window_ms must be a positive multiple of 20")
        self._session_id = session_id
        self._enhancer = enhancer
        self._frames_per_window = window_ms // 20
        self._frames: list[bytes] = []
        self._inference: asyncio.Task[tuple[bytes, ...]] | None = None

    async def push_async(self, frame: bytes) -> tuple[bytes, ...]:
        """Bound live inference to the audio duration, with one call in flight."""
        self._validate_frame(frame)
        self._frames.append(frame)
        if len(self._frames) < self._frames_per_window:
            return ()
        return await self.flush_async()

    async def flush_async(self) -> tuple[bytes, ...]:
        if not self._frames:
            return ()
        frames = tuple(self._frames)
        self._frames.clear()
        previous = self._inference
        if previous is not None:
            if not previous.done():
                LOGGER.debug("zipenhancer session=%s outcome=busy_raw frames=%d", self._session_id, len(frames))
                return frames
            # A timed-out result is never inserted into a later audio window.
            _ = previous.result()
        task = asyncio.create_task(asyncio.to_thread(self._process_frames, frames))
        self._inference = task
        done, _ = await asyncio.wait((task,), timeout=len(frames) * 0.020)
        if done:
            self._inference = None
            return task.result()
        LOGGER.debug("zipenhancer session=%s outcome=deadline_raw frames=%d", self._session_id, len(frames))
        return frames

    async def aclose(self) -> None:
        """Drain the one CPU call before its model can be reused after reconnect."""
        task = self._inference
        if task is not None:
            _ = await asyncio.shield(task)
            self._inference = None
        self._frames.clear()

    def push(self, frame: bytes) -> tuple[bytes, ...]:
        self._validate_frame(frame)
        self._frames.append(frame)
        if len(self._frames) < self._frames_per_window:
            return ()
        return self._process_window()

    def flush(self) -> tuple[bytes, ...]:
        if not self._frames:
            return ()
        return self._process_window()

    def reset(self) -> None:
        self._frames.clear()

    def _process_window(self) -> tuple[bytes, ...]:
        frames = tuple(self._frames)
        self._frames.clear()
        return self._process_frames(frames)

    def _process_frames(self, frames: tuple[bytes, ...]) -> tuple[bytes, ...]:
        raw = b"".join(frames)
        try:
            enhanced = self._enhancer.enhance(raw)
            if len(enhanced) != len(raw):
                raise ValueError("enhanced PCM length changed")
        except Exception:
            LOGGER.exception(
                "ZipEnhancer window failed; forwarding raw PCM",
                extra={"frame_count": len(frames)},
            )
            return frames
        return tuple(
            enhanced[offset : offset + PCM16_20MS_FRAME_BYTES]
            for offset in range(0, len(enhanced), PCM16_20MS_FRAME_BYTES)
        )

    @staticmethod
    def _validate_frame(frame: bytes) -> None:
        if len(frame) != PCM16_20MS_FRAME_BYTES:
            raise ConfigError(
                key="capture.block", reason="must contain exactly 640 PCM16 bytes"
            )


_N_FFT = 400
_HOP = 100
_COMPRESS = 0.3


def _mag_pha_stft(samples: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray, int]:
    padded = samples.size + _N_FFT
    signal = numpy.pad(samples, (_N_FFT // 2, _N_FFT // 2), mode="reflect")
    window = numpy.hanning(_N_FFT + 1)[:-1].astype(numpy.float32)
    count = 1 + (signal.size - _N_FFT) // _HOP
    frames = numpy.stack(
        [
            signal[index * _HOP : index * _HOP + _N_FFT] * window
            for index in range(count)
        ]
    )
    spectrum = numpy.fft.rfft(frames, axis=1).T
    magnitude = numpy.sqrt(spectrum.real**2 + spectrum.imag**2 + 1e-9)
    phase = numpy.arctan2(spectrum.imag, spectrum.real + 1e-5)
    return magnitude.astype(numpy.float32) ** _COMPRESS, phase.astype(numpy.float32), padded


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
    """Stateful Silero VAD ONNX adapter following the official ONNX wrapper."""

    _session: onnxruntime.InferenceSession
    _input_name: str
    _state_name: str
    _sample_rate_name: str
    _state: numpy.ndarray
    _context: numpy.ndarray

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
            numpy.zeros((1, SILERO_VAD_CONTEXT_SAMPLES), dtype=numpy.float32),
        )

    def speech_probability(self, pcm16le: bytes) -> float:
        samples = numpy.frombuffer(pcm16le, dtype="<i2").astype(numpy.float32) / 32768
        if samples.size != SILERO_VAD_WINDOW_SAMPLES:
            raise ConfigError(key="MIC_VAD_MODEL_PATH", reason="requires 512 samples")
        model_input = numpy.concatenate(
            (self._context, samples[numpy.newaxis, :]), axis=1
        )
        output, state = self._session.run(
            None,
            {
                self._input_name: model_input,
                self._state_name: self._state,
                self._sample_rate_name: numpy.array(SAMPLE_RATE_HZ, dtype=numpy.int64),
            },
        )
        self._state = numpy.asarray(state)
        self._context = model_input[:, -SILERO_VAD_CONTEXT_SAMPLES:]
        return float(numpy.asarray(output).reshape(-1)[0])

    def reset(self) -> None:
        self._state = numpy.zeros((2, 1, 128), dtype=numpy.float32)
        self._context = numpy.zeros(
            (1, SILERO_VAD_CONTEXT_SAMPLES), dtype=numpy.float32
        )
