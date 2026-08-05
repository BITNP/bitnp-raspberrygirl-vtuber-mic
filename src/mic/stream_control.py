import json
import logging
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol, cast
from urllib.parse import urlparse
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from mic.config import ConfigError, ServiceConfig
from mic.tls import build_tls_context

SCHEMA_VERSION: Final = "1.0.0"

VOICE_EVIDENCE_EVENT: Final = "voice.evidence"

ASR_PARTIAL_EVENT: Final = "asr.partial"

ASR_FINAL_EVENT: Final = "asr.final"

MAX_EMBEDDING_DIMENSIONS: Final = 1_024
MAX_RTP_TIMESTAMP: Final = (1 << 32) - 1
MAX_ASR_SPAN_SAMPLES: Final = 16_000 * 30
MAX_EVIDENCE_SPAN_SAMPLES: Final = 16_000 * 2
MAX_CONTROL_FRAME_BYTES: Final = 64 * 1024
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ControlContext:
    trace_id: str

    session_id: str


@dataclass(frozen=True, slots=True)
class VoiceEvidence:
    stream_id: str
    input_epoch: int
    rtp_start_timestamp: int
    rtp_end_timestamp: int
    embedding_model_revision: str
    embedding: tuple[float, ...]
    speech_ms: int
    quality_score: float

    def __post_init__(self) -> None:
        if (
            not self.stream_id
            or self.input_epoch < 0
            or not _valid_rtp_span(
                self.rtp_start_timestamp,
                self.rtp_end_timestamp,
                MAX_EVIDENCE_SPAN_SAMPLES,
            )
            or not self.embedding_model_revision
            or not 1 <= len(self.embedding) <= MAX_EMBEDDING_DIMENSIONS
            or self.speech_ms <= 0
            or not 0 <= self.quality_score <= 1
        ):
            raise ConfigError(key=VOICE_EVIDENCE_EVENT, reason="invalid evidence")


@dataclass(frozen=True, slots=True)
class AsrResult:
    """A bounded endpoint recognition result sent only over Mic control."""

    stream_id: str
    segment_id: str
    rtp_start_timestamp: int
    rtp_end_timestamp: int
    cancellation_epoch: int
    text: str
    received_at_ms: int
    confidence: float | None = None

    def __post_init__(self) -> None:
        if (
            not self.stream_id
            or not self.segment_id
            or not _valid_rtp_span(
                self.rtp_start_timestamp,
                self.rtp_end_timestamp,
                MAX_ASR_SPAN_SAMPLES,
            )
            or self.cancellation_epoch < 0
            or self.received_at_ms < 0
            or not self.text.strip()
            or len(self.text) > 4_000
            or self.confidence is not None and not 0 <= self.confidence <= 1
        ):
            raise ConfigError(key=ASR_FINAL_EVENT, reason="invalid ASR result")


class ControlConnection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


class ControlConnector(Protocol):
    async def connect(
        self,
        url: str,
        headers: dict[str, str],
        ssl_context: ssl.SSLContext | None,
    ) -> ControlConnection: ...


class WebsocketsControlConnector:
    async def connect(
        self,
        url: str,
        headers: dict[str, str],
        ssl_context: ssl.SSLContext | None,
    ) -> ControlConnection:

        if urlparse(url).scheme != "wss" or ssl_context is None:
            return await connect(url, additional_headers=headers)

        return await connect(url, additional_headers=headers, ssl=ssl_context)


class WebSocketStreamingControl:
    __slots__ = ("_abnormal_close", "_connection", "_context", "_input_epoch")

    def __init__(self, connection: ControlConnection, context: ControlContext) -> None:

        self._connection = connection

        self._context = context
        self._input_epoch: int | None = None
        self._abnormal_close = False

    @classmethod
    async def open(
        cls,
        service_config: ServiceConfig,
        context: ControlContext,
        connector: ControlConnector | None = None,
    ) -> "WebSocketStreamingControl":

        tls_context = (
            build_tls_context(service_config.tls_ca_path)
            if urlparse(service_config.orchestrator_ws_url).scheme == "wss"
            else None
        )
        resolved_connector = (
            WebsocketsControlConnector() if connector is None else connector
        )
        connection = await resolved_connector.connect(
            service_config.orchestrator_ws_url,
            _authorization_header(service_config),
            tls_context,
        )
        _LOGGER.debug(
            "mic_control_connected url=%s session=%s",
            service_config.orchestrator_ws_url,
            context.session_id,
        )

        return cls(connection, context)

    async def register_input(self, stream_id: str) -> int:
        """Register the control-only Mic input; no audio endpoint is exposed."""
        if not stream_id:
            raise ConfigError(key="mic.input.register", reason="stream_id is required")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "mic.input.register",
            "event_id": str(uuid4()),
            "source": "mic",
            "time": datetime.now(UTC).isoformat(),
            "trace_id": self._context.trace_id,
            "session_id": self._context.session_id,
            "seq": 0,
            "data": {"stream_id": stream_id},
        }
        await self._connection.send(json.dumps(event, separators=(",", ":")))
        message = await self._connection.recv()
        if not isinstance(message, str) or len(message.encode("utf-8")) > MAX_CONTROL_FRAME_BYTES:
            raise ConfigError(key="mic.input.ready", reason="invalid control frame")
        try:
            decoded = json.loads(message)
        except json.JSONDecodeError as error:
            raise ConfigError(key="mic.input.ready", reason="invalid JSON") from error
        ready = cast("object", decoded)
        parsed = cast("dict[str, object]", ready) if isinstance(ready, dict) else None
        data_value = parsed.get("data") if parsed is not None else None
        data = (
            cast("dict[str, object]", data_value)
            if isinstance(data_value, dict)
            else None
        )
        epoch = data.get("input_epoch") if data is not None else None
        if (
            parsed is None
            or parsed.get("event_type") != "mic.input.ready"
            or parsed.get("source") != "orchestrator"
            or parsed.get("session_id") != self._context.session_id
            or data is None
            or data.get("stream_id") != stream_id
            or type(epoch) is not int
            or epoch < 0
        ):
            raise ConfigError(key="mic.input.ready", reason="invalid readiness lease")
        self._input_epoch = epoch
        return epoch

    async def wait_closed(self) -> None:
        """Wait for the control peer to close without interpreting inbound effects."""
        try:
            while True:
                _ = await self._connection.recv()
        except ConnectionClosed as error:
            self._abnormal_close = getattr(error, "code", 1006) not in {1000, 1001}
            _LOGGER.debug("mic_control_peer_closed session=%s", self._context.session_id)

    @property
    def should_reconnect(self) -> bool:
        return self._abnormal_close

    async def send_voice_evidence(
        self, evidence: VoiceEvidence, *, sequence: int
    ) -> None:
        if sequence < 0:
            raise ConfigError(key=VOICE_EVIDENCE_EVENT, reason="invalid sequence")
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": VOICE_EVIDENCE_EVENT,
            "event_id": str(uuid4()),
            "source": "mic",
            "time": datetime.now(UTC).isoformat(),
            "trace_id": self._context.trace_id,
            "session_id": self._context.session_id,
            "seq": sequence,
            "data": {
                "stream_id": evidence.stream_id,
                "input_epoch": evidence.input_epoch,
                "rtp_start_timestamp": evidence.rtp_start_timestamp,
                "rtp_end_timestamp": evidence.rtp_end_timestamp,
                "embedding_model_revision": evidence.embedding_model_revision,
                "embedding": list(evidence.embedding),
                "quality": {
                    "speech_ms": evidence.speech_ms,
                    "score": evidence.quality_score,
                },
            },
        }
        await self._connection.send(json.dumps(event, separators=(",", ":")))

    async def send_asr_partial(self, result: AsrResult, *, sequence: int) -> None:
        await self._send_asr(ASR_PARTIAL_EVENT, result, sequence)

    async def send_asr_final(self, result: AsrResult, *, sequence: int) -> None:
        await self._send_asr(ASR_FINAL_EVENT, result, sequence)

    async def _send_asr(
        self, event_type: str, result: AsrResult, sequence: int
    ) -> None:
        if sequence < 0:
            raise ConfigError(key=event_type, reason="invalid sequence")
        data: dict[str, object] = {
            "stream_id": result.stream_id,
            "segment_id": result.segment_id,
            "rtp_start_timestamp": result.rtp_start_timestamp,
            "rtp_end_timestamp": result.rtp_end_timestamp,
            "cancellation_epoch": result.cancellation_epoch,
            "text": result.text,
            "received_at_ms": result.received_at_ms,
        }
        if result.confidence is not None:
            data["confidence"] = result.confidence
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": event_type,
            "event_id": str(uuid4()),
            "source": "mic",
            "time": datetime.now(UTC).isoformat(),
            "trace_id": self._context.trace_id,
            "session_id": self._context.session_id,
            "seq": sequence,
            "data": data,
        }
        await self._connection.send(json.dumps(event, separators=(",", ":")))

    async def aclose(self) -> None:
        _LOGGER.debug("mic_control_closed session=%s", self._context.session_id)
        await self._connection.close()


def _authorization_header(config: ServiceConfig) -> dict[str, str]:

    token = config.trusted_lan_token

    if token is None:
        return {}

    return {"Authorization": f"Bearer {token}"}


def _valid_rtp_span(start: int, end: int, maximum: int) -> bool:
    return (
        0 <= start <= MAX_RTP_TIMESTAMP
        and 0 <= end <= MAX_RTP_TIMESTAMP
        and 0 < ((end - start) & MAX_RTP_TIMESTAMP) <= maximum
    )
