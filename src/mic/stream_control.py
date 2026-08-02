import json
import logging
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from websockets.asyncio.client import connect

from mic.config import ConfigError, ServiceConfig
from mic.rtp import MIC_RTP_SSRC
from mic.streaming import SourceRegistration
from mic.tls import build_tls_context

SCHEMA_VERSION: Final = "1.0.0"

SOURCE_READY_EVENT: Final = "media.rtp.source.ready"

SOURCE_REGISTER_EVENT: Final = "media.rtp.source.register"

SOURCE_STOP_EVENT: Final = "media.rtp.source.stop"

SOUND_FLUSH_EVENT: Final = "media.stream.flush"

VOICE_EVIDENCE_EVENT: Final = "voice.evidence"

ASR_PARTIAL_EVENT: Final = "asr.partial"

ASR_FINAL_EVENT: Final = "asr.final"

MAX_EMBEDDING_DIMENSIONS: Final = 1_024
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ControlContext:
    trace_id: str

    session_id: str


@dataclass(frozen=True, slots=True)
class VoiceEvidence:
    stream_id: str
    rtp_start_timestamp: int
    rtp_end_timestamp: int
    embedding_model_revision: str
    embedding: tuple[float, ...]
    speech_ms: int
    quality_score: float

    def __post_init__(self) -> None:
        if (
            not self.stream_id
            or self.rtp_start_timestamp < 0
            or self.rtp_end_timestamp < self.rtp_start_timestamp
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
            or self.rtp_start_timestamp < 0
            or self.rtp_end_timestamp < self.rtp_start_timestamp
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
    __slots__ = ("_connection", "_context", "_highest_stop_epochs")

    def __init__(self, connection: ControlConnection, context: ControlContext) -> None:

        self._connection = connection

        self._context = context

        self._highest_stop_epochs: dict[str, int] = {}

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

    async def register_source(self, registration: SourceRegistration) -> None:

        event = {
            "schema_version": SCHEMA_VERSION,
            "event_type": SOURCE_REGISTER_EVENT,
            "event_id": str(uuid4()),
            "source": "mic",
            "time": datetime.now(UTC).isoformat(),
            "trace_id": self._context.trace_id,
            "session_id": self._context.session_id,
            "seq": 0,
            "data": {
                "stream_id": registration.stream_id,
                "ssrc": int(MIC_RTP_SSRC),
                "codec": {
                    "format": "L16",
                    "clock_rate_hz": 16000,
                    "channels": 1,
                    "payload_type": 96,
                    "samples_per_frame": 320,
                },
                "rtp_endpoint": {
                    "host": registration.rtp_endpoint.host,
                    "port": int(registration.rtp_endpoint.port),
                },
            },
        }

        await self._connection.send(json.dumps(event, separators=(",", ":")))
        _LOGGER.debug(
            "mic_control_sent event=%s stream=%s",
            SOURCE_REGISTER_EVENT,
            registration.stream_id,
        )

    async def register_input(self, stream_id: str) -> None:
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

    async def wait_source_ready(self, registration: SourceRegistration) -> None:

        raw_event = await self._connection.recv()
        _LOGGER.debug(
            "mic_control_received event=media.rtp.source.ready bytes=%d", len(raw_event)
        )

        if not isinstance(raw_event, str):
            raise ConfigError(
                key="media.rtp.source.ready", reason="must be a text control event"
            )

        try:
            event = json.loads(raw_event)

        except json.JSONDecodeError as error:
            raise ConfigError(
                key="media.rtp.source.ready", reason="must be a text control event"
            ) from error

        if not isinstance(event, dict) or event.get("event_type") != SOURCE_READY_EVENT:
            raise ConfigError(
                key="media.rtp.source.ready",
                reason="must be received before RTP delivery",
            )

        data = event.get("data")

        if not isinstance(data, dict):
            raise ConfigError(key="media.rtp.source.ready", reason="must contain data")

        if data.get("stream_id") != registration.stream_id or data.get("ssrc") != int(
            MIC_RTP_SSRC
        ):
            raise ConfigError(
                key="media.rtp.source.ready",
                reason="must confirm the registered stream and SSRC",
            )

    async def wait_stop(self, registration: SourceRegistration) -> int:

        while True:
            raw_event = await self._connection.recv()
            _LOGGER.debug("mic_control_received bytes=%d", len(raw_event))

            if not isinstance(raw_event, str):
                raise ConfigError(
                    key=SOURCE_STOP_EVENT, reason="must be a text control event"
                )

            try:
                event = json.loads(raw_event)

            except json.JSONDecodeError as error:
                raise ConfigError(
                    key=SOURCE_STOP_EVENT, reason="must be a text control event"
                ) from error

            if isinstance(event, dict) and event.get("event_type") == SOUND_FLUSH_EVENT:
                continue

            if (
                not isinstance(event, dict)
                or event.get("event_type") != SOURCE_STOP_EVENT
            ):
                raise ConfigError(
                    key=SOURCE_STOP_EVENT,
                    reason="must be received after source readiness",
                )

            if (
                event.get("source") != "orchestrator"
                or event.get("session_id") != self._context.session_id
            ):
                raise ConfigError(
                    key=SOURCE_STOP_EVENT,
                    reason="must be authenticated for this session",
                )

            data = event.get("data")

            if (
                not isinstance(data, dict)
                or data.get("stream_id") != registration.stream_id
            ):
                raise ConfigError(
                    key=SOURCE_STOP_EVENT, reason="must target the registered stream"
                )

            epoch = data.get("cancellation_epoch")

            if type(epoch) is not int or epoch < 0:
                raise ConfigError(
                    key=SOURCE_STOP_EVENT,
                    reason="must contain a nonnegative cancellation epoch",
                )

            previous_epoch = self._highest_stop_epochs.get(registration.stream_id)

            if previous_epoch is not None and epoch <= previous_epoch:
                raise ConfigError(
                    key=SOURCE_STOP_EVENT,
                    reason="must contain a newer cancellation epoch",
                )

            self._highest_stop_epochs[registration.stream_id] = epoch

            return epoch

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
