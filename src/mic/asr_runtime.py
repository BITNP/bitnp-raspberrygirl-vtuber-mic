from __future__ import annotations

from time import monotonic_ns

from mic.asr import AsrEndpoint, EnergyEndpointDetector, OpenAICompatibleAsr
from mic.camplusplus import CamPlusPlusOnnx
from mic.speech_models import SileroVadOnnx, ZipEnhancerOnnx
from mic.stream_control import AsrResult, VoiceEvidence, WebSocketStreamingControl


class MicAsrEndpointProcessor:
    """Turns endpointed Mic frames into final control events, never media effects."""

    def __init__(
        self,
        control: WebSocketStreamingControl,
        *,
        stream_id: str,
        asr: OpenAICompatibleAsr,
        camplusplus: CamPlusPlusOnnx | None = None,
        enhancer: ZipEnhancerOnnx | None = None,
        vad: SileroVadOnnx | None = None,
        asr_endpoint_includes_vad: bool = False,
        cancellation_epoch: int = 0,
    ) -> None:
        self._control = control
        self._stream_id = stream_id
        self._asr = asr
        self._camplusplus = camplusplus
        self._enhancer = enhancer
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

    async def push(self, frame: bytes, rtp_timestamp: int) -> None:
        endpoint = self._detector.push(
            frame,
            rtp_timestamp,
            speech=self._speech(frame),
        )
        if endpoint is not None:
            await self._recognize(endpoint)

    async def flush(self) -> None:
        endpoint = self._detector.flush()
        if endpoint is not None:
            await self._recognize(endpoint)

    def _speech(self, frame: bytes) -> bool | None:
        if self._asr_endpoint_includes_vad:
            return True
        vad = self._vad
        if vad is None:
            return None
        self._vad_buffer += frame
        if len(self._vad_buffer) >= 1024:
            self._last_vad_speech = vad.speech_probability(self._vad_buffer[:1024]) >= 0.5
            self._vad_buffer = self._vad_buffer[1024:]
        return self._last_vad_speech

    async def _recognize(self, endpoint: object) -> None:
        # Detector output is intentionally opaque at the streaming boundary;
        # the ASR adapter alone receives temporary PCM bytes.

        if not isinstance(endpoint, AsrEndpoint):
            return
        enhancer = self._enhancer
        if enhancer is not None:
            endpoint = AsrEndpoint(
                enhancer.enhance(endpoint.pcm16le),
                endpoint.rtp_start_timestamp,
                endpoint.rtp_end_timestamp,
            )
        recognition = await self._asr.transcribe(endpoint)
        camplusplus = self._camplusplus
        if camplusplus is not None:
            embedding = camplusplus.embed(endpoint)
            await self._control.send_voice_evidence(
                VoiceEvidence(
                    stream_id=self._stream_id,
                    rtp_start_timestamp=endpoint.rtp_start_timestamp,
                    rtp_end_timestamp=endpoint.rtp_end_timestamp,
                    embedding_model_revision=camplusplus.revision,
                    embedding=embedding.values,
                    speech_ms=len(endpoint.pcm16le) * 1000 // 32_000,
                    quality_score=embedding.quality_score,
                ),
                sequence=self._sequence,
            )
            self._sequence += 1
        if not recognition.text:
            return
        self._segment += 1
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
