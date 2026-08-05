"""Mic-owned endpointing and OpenAI-compatible ASR boundary.

This module intentionally accepts PCM windows, never RTP packets or a peer
socket.  It keeps raw audio in memory only until the single ASR request ends.
"""

from __future__ import annotations

import json
import math
import wave
from dataclasses import dataclass
from io import BytesIO
from typing import cast

import httpx

from mic.config import ConfigError

SAMPLE_RATE_HZ = 16_000
FRAME_BYTES = 640
MAX_RESPONSE_BYTES = 65_536


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
    """Small stdlib-only OpenAI-compatible transcription client.

    ``endpoint`` is the provider base URL (for example, ``https://asr.example/v1``).
    The OpenAI-compatible transcription path is owned by this adapter.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint or not model:
            raise ConfigError(key="MIC_ASR_ENDPOINT", reason="endpoint and model required")
        self._endpoint = f"{endpoint.rstrip('/')}/audio/transcriptions"
        self._model = model
        self._api_key = api_key
        self._client = (
            httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
                trust_env=False,
            )
            if client is None
            else client
        )
        self._owns_client = client is None

    async def transcribe(self, endpoint: AsrEndpoint) -> Recognition:
        wav = _wav(endpoint.pcm16le)
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                headers=headers,
                data={"model": self._model},
                files={"file": ("utterance.wav", wav, "audio/wav")},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return Recognition("")
        except (httpx.HTTPError, OSError):
            return Recognition("")
        try:
            value = cast("object", json.loads(body))
        except (json.JSONDecodeError, UnicodeError, ValueError):
            return Recognition("")
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            return Recognition("")
        confidence = value.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            return Recognition("")
        return Recognition(
            value["text"].strip(),
            None if confidence is None else float(confidence),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


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

    def reset(self) -> None:
        self._frames.clear()
        self._start = None
        self._last_end = 0
        self._silence = 0


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
