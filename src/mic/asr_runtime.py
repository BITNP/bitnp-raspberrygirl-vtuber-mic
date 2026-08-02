from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic_ns

from mic.asr import AsrEndpoint, EnergyEndpointDetector, OpenAICompatibleAsr
from mic.camplusplus import CamPlusPlusEmbedding, CamPlusPlusWindow
from mic.speech_models import SileroVadOnnx
from mic.stream_control import AsrResult, VoiceEvidence, WebSocketStreamingControl


class MicAsrEndpointProcessor:
    """Turns endpointed Mic frames into final control events, never media effects."""

    def __init__(
        self,
        control: WebSocketStreamingControl,
        *,
        stream_id: str,
        asr: OpenAICompatibleAsr,
        vad: SileroVadOnnx | None = None,
        asr_endpoint_includes_vad: bool = False,
        cancellation_epoch: int = 0,
    ) -> None:
        self._control = control
        self._stream_id = stream_id
        self._asr = asr
        self._vad = vad
        self._asr_endpoint_includes_vad = asr_endpoint_includes_vad
        self._vad_buffer = b""
        self._last_vad_speech = False
        self._epoch = cancellation_epoch
        # The OpenAI-compatible multipart transcription boundary is batch-only.
        # When it owns VAD, submit bounded two-second windows instead of keeping
        # an unbounded capture until the device closes.
        self._detector = EnergyEndpointDetector(
            max_frames=100 if asr_endpoint_includes_vad else 1_500
        )
        self._sequence = 1
        self._segment = 0
        self._send_lock = asyncio.Lock()

    async def push(self, frame: bytes, rtp_timestamp: int) -> None:
        endpoint = self.push_enhanced_frame(frame, rtp_timestamp)
        if endpoint is not None:
            await self.recognize_endpoint(endpoint)

    def push_enhanced_frame(
        self, frame: bytes, rtp_timestamp: int
    ) -> AsrEndpoint | None:
        """Accept one already enhanced 20 ms PCM frame and return a completed segment."""
        return self.analyze_enhanced_frame(frame, rtp_timestamp).endpoint

    def analyze_enhanced_frame(self, frame: bytes, rtp_timestamp: int) -> FrameAnalysis:
        """Run the stateful VAD once and share its result with all consumers."""
        vad_speech = self._speech(frame)
        endpoint_speech = True if self._asr_endpoint_includes_vad else vad_speech
        return FrameAnalysis(
            speech=False if vad_speech is None else vad_speech,
            endpoint=self._detector.push(frame, rtp_timestamp, speech=endpoint_speech),
        )

    async def flush(self) -> None:
        endpoint = self.flush_enhanced_frames()
        if endpoint is not None:
            await self.recognize_endpoint(endpoint)

    def flush_enhanced_frames(self) -> AsrEndpoint | None:
        """Finish the current enhanced VAD segment without stopping capture."""
        return self._detector.flush()

    def _speech(self, frame: bytes) -> bool | None:
        vad = self._vad
        if vad is None:
            return None
        self._vad_buffer += frame
        if len(self._vad_buffer) >= 1024:
            self._last_vad_speech = vad.speech_probability(self._vad_buffer[:1024]) >= 0.5
            self._vad_buffer = self._vad_buffer[1024:]
        return self._last_vad_speech

    async def recognize_endpoint(self, endpoint: object) -> None:
        # Detector output is intentionally opaque at the streaming boundary;
        # the ASR adapter alone receives temporary PCM bytes.

        if not isinstance(endpoint, AsrEndpoint):
            return
        recognition = await self._asr.transcribe(endpoint)
        if not recognition.text:
            return
        self._segment += 1
        async with self._send_lock:
            await self._control.send_asr_final(
                AsrResult(
                    stream_id=self._stream_id,
                    segment_id=f"asr-{self._segment}",
                    rtp_start_timestamp=endpoint.rtp_start_timestamp,
                    rtp_end_timestamp=endpoint.rtp_end_timestamp,
                    cancellation_epoch=self._epoch,
                    text=recognition.text,
                    received_at_ms=monotonic_ns() // 1_000_000,
                    confidence=recognition.confidence,
                ),
                sequence=self._sequence,
            )
            self._sequence += 1

    async def emit_voice_evidence(
        self, window: CamPlusPlusWindow, embedding: CamPlusPlusEmbedding, revision: str
    ) -> None:
        async with self._send_lock:
            await self._control.send_voice_evidence(
                VoiceEvidence(
                    stream_id=self._stream_id,
                    rtp_start_timestamp=window.rtp_start_timestamp,
                    rtp_end_timestamp=window.rtp_end_timestamp,
                    embedding_model_revision=revision,
                    embedding=embedding.values,
                    speech_ms=window.speech_ms,
                    quality_score=min(1.0, window.speech_ms / 1_500),
                ),
                sequence=self._sequence,
            )
            self._sequence += 1


@dataclass(frozen=True, slots=True)
class FrameAnalysis:
    speech: bool
    endpoint: AsrEndpoint | None
