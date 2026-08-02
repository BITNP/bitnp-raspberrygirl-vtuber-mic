from __future__ import annotations

from time import monotonic_ns

from mic.asr import EnergyEndpointDetector, OpenAICompatibleAsr
from mic.stream_control import AsrResult, WebSocketStreamingControl


class MicAsrEndpointProcessor:
    """Turns endpointed Mic frames into final control events, never media effects."""

    def __init__(
        self,
        control: WebSocketStreamingControl,
        *,
        stream_id: str,
        asr: OpenAICompatibleAsr,
        cancellation_epoch: int = 0,
    ) -> None:
        self._control = control
        self._stream_id = stream_id
        self._asr = asr
        self._epoch = cancellation_epoch
        self._detector = EnergyEndpointDetector()
        self._sequence = 1
        self._segment = 0

    async def push(self, frame: bytes, rtp_timestamp: int) -> None:
        endpoint = self._detector.push(frame, rtp_timestamp)
        if endpoint is not None:
            await self._recognize(endpoint)

    async def flush(self) -> None:
        endpoint = self._detector.flush()
        if endpoint is not None:
            await self._recognize(endpoint)

    async def _recognize(self, endpoint: object) -> None:
        # Detector output is intentionally opaque at the streaming boundary;
        # the ASR adapter alone receives temporary PCM bytes.
        from mic.asr import AsrEndpoint

        if not isinstance(endpoint, AsrEndpoint):
            return
        recognition = await self._asr.transcribe(endpoint)
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
