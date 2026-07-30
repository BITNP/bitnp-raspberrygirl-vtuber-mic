
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import uuid4

from websockets.asyncio.client import connect

from mic.config import ConfigError, ServiceConfig
from mic.rtp import MIC_RTP_SSRC
from mic.streaming import SourceRegistration

SCHEMA_VERSION: Final = "1.0.0"

SOURCE_READY_EVENT: Final = "media.rtp.source.ready"

SOURCE_REGISTER_EVENT: Final = "media.rtp.source.register"

SOURCE_STOP_EVENT: Final = "media.rtp.source.stop"

SOUND_FLUSH_EVENT: Final = "media.stream.flush"


@dataclass(frozen=True, slots=True)
class ControlContext:

    trace_id: str

    session_id: str


class ControlConnection(Protocol):

    async def send(self, message: str) -> None:

        ...

    async def recv(self) -> str | bytes:

        ...

    async def close(self) -> None:

        ...


class WebSocketStreamingControl:

    __slots__ = ("_connection", "_context", "_highest_stop_epochs")

    def __init__(self, connection: ControlConnection, context: ControlContext) -> None:

        self._connection = connection

        self._context = context

        self._highest_stop_epochs: dict[str, int] = {}

    @classmethod
    async def open(
        cls, service_config: ServiceConfig, context: ControlContext
    ) -> "WebSocketStreamingControl":

        connection = await connect(
            service_config.orchestrator_ws_url,
            additional_headers=_authorization_header(service_config),
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

    async def wait_source_ready(self, registration: SourceRegistration) -> None:

        raw_event = await self._connection.recv()

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

    async def aclose(self) -> None:

        await self._connection.close()


def _authorization_header(config: ServiceConfig) -> dict[str, str]:

    token = config.trusted_lan_token

    if token is None:
        return {}

    return {"Authorization": f"Bearer {token}"}
