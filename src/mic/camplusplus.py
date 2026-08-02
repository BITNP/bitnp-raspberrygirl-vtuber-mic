"""CPU-only CAM++ ONNX embedding boundary owned by Mic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy
import onnxruntime

from mic.asr import AsrEndpoint
from mic.config import ConfigError


@dataclass(frozen=True, slots=True)
class CamPlusPlusEmbedding:
    values: tuple[float, ...]
    quality_score: float


class CamPlusPlusOnnx:
    """Runs a controlled local CAM++ ONNX file on endpointed PCM only."""

    def __init__(self, model_path: Path, revision: str) -> None:
        if not model_path.is_file() or not revision.strip():
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="model and revision required")
        self.revision = revision.strip()
        self._session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        inputs = self._session.get_inputs()
        if len(inputs) != 1:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="model must have one audio input")
        self._input_name = inputs[0].name
        self._input_rank = len(inputs[0].shape)

    def embed(self, endpoint: AsrEndpoint) -> CamPlusPlusEmbedding:
        samples = numpy.frombuffer(endpoint.pcm16le, dtype="<i2").astype(numpy.float32)
        samples /= 32768.0
        if self._input_rank == 3:
            audio = samples[numpy.newaxis, numpy.newaxis, :]
        elif self._input_rank == 2:
            audio = samples[numpy.newaxis, :]
        else:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="unsupported audio input rank")
        output = numpy.asarray(self._session.run(None, {self._input_name: audio})[0])
        embedding = output.reshape(-1).astype(numpy.float64)
        norm = float(numpy.linalg.norm(embedding))
        if norm == 0 or embedding.size > 1024:
            raise ConfigError(key="MIC_CAMPP_MODEL_PATH", reason="invalid embedding output")
        embedding /= norm
        # The detector admitted speech; normalized energy supplies a bounded
        # quality hint without retaining the raw waveform.
        quality = min(1.0, float(numpy.mean(numpy.abs(samples))) * 8.0)
        return CamPlusPlusEmbedding(tuple(float(value) for value in embedding), quality)
