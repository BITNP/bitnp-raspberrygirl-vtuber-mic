"""Mic-owned endpointing and OpenAI-compatible ASR boundary.

This module intentionally accepts PCM windows, never RTP packets or a peer
socket.  It keeps raw audio in memory only until the single ASR request ends.
"""

from __future__ import annotations

import asyncio
import json
import wave
from dataclasses import dataclass
from io import BytesIO
from urllib.request import Request, urlopen

from mic.config import ConfigError

SAMPLE_RATE_HZ = 16_000
FRAME_BYTES = 640


@dataclass(frozen=True, slots=True)
class AsrEndpoint:
    pcm16le: bytes
    rtp_start_timestamp: int
    rtp_end_timestamp: int


@dataclass(frozen=True, slots=True)
class Recognition:
    text: str
    confidence: float | None = None


class OpenAICompatibleAsr:
    """Small stdlib-only OpenAI-compatible ``/audio/transcriptions`` client."""

    def __init__(self, endpoint: str, model: str, api_key: str | None = None) -> None:
        if not endpoint or not model:
            raise ConfigError(key="MIC_ASR_ENDPOINT", reason="endpoint and model required")
        self._endpoint = endpoint
        self._model = model
        self._api_key = api_key

    async def transcribe(self, endpoint: AsrEndpoint) -> Recognition:
        return await asyncio.to_thread(self._transcribe, endpoint)

    def _transcribe(self, endpoint: AsrEndpoint) -> Recognition:
        boundary = "----bitnp-mic-asr"
        wav = _wav(endpoint.pcm16le)
        body = b"".join(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self._model}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"utterance.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode(),
                wav,
                f"\r\n--{boundary}--\r\n".encode(),
            )
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(self._endpoint, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=15) as response:
            value = json.loads(response.read())
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise ConfigError(key="MIC_ASR_ENDPOINT", reason="response lacks text")
        confidence = value.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            confidence = None
        return Recognition(value["text"].strip(), None if confidence is None else float(confidence))


class EnergyEndpointDetector:
    """VAD/endpoint detector with a hard cap for fixed 20 ms PCM16 frames."""

    def __init__(
        self,
        *,
        threshold: int = 300,
        trailing_silence_frames: int = 20,
        max_frames: int = 1_500,
    ) -> None:
        if max_frames < 1:
            raise ValueError("max_frames must be positive")
        self._threshold = threshold
        self._trailing_silence_frames = trailing_silence_frames
        self._max_frames = max_frames
        self._frames: list[bytes] = []
        self._start: int | None = None
        self._last_end = 0
        self._silence = 0

    def push(
        self, frame: bytes, rtp_timestamp: int, *, speech: bool | None = None
    ) -> AsrEndpoint | None:
        if len(frame) != FRAME_BYTES:
            raise ConfigError(key="capture.block", reason="must contain exactly 640 PCM16 bytes")
        is_speech = _energy(frame) >= self._threshold if speech is None else speech
        if is_speech and self._start is None:
            self._start = rtp_timestamp
        if self._start is None:
            return None
        self._frames.append(frame)
        self._last_end = (rtp_timestamp + 320) % (1 << 32)
        self._silence = 0 if is_speech else self._silence + 1
        if len(self._frames) >= self._max_frames:
            return self.flush()
        if self._silence < self._trailing_silence_frames:
            return None
        return self.flush()

    def flush(self) -> AsrEndpoint | None:
        if self._start is None:
            return None
        result = AsrEndpoint(b"".join(self._frames), self._start, self._last_end)
        self._frames = []
        self._start = None
        self._silence = 0
        return result


def _energy(frame: bytes) -> int:
    samples = memoryview(frame).cast("h")
    return sum(abs(sample) for sample in samples) // len(samples)


def _wav(pcm16le: bytes) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE_HZ)
        wav.writeframes(pcm16le)
    return output.getvalue()
