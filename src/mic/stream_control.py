import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect

from mic.config import ConfigError, ServiceConfig
from mic.orchestrator_ws import MIC_RTP_SSRC
from mic.streaming import SourceRegistration

SCHEMA_VERSION: Final = "1.0.0"
SOURCE_READY_EVENT: Final = "media.rtp.source.ready"
SOURCE_REGISTER_EVENT: Final = "media.rtp.source.register"


@dataclass(frozen=True, slots=True)
class ControlContext:
    trace_id: str
    session_id: str


class WebSocketStreamingControl:
    __slots__ = ("_connection", "_context")

    def __init__(self, connection: ClientConnection, context: ControlContext) -> None:
        self._connection = connection
        self._context = context

    @classmethod
    async def open(cls, service_config: ServiceConfig, context: ControlContext) -> "WebSocketStreamingControl":
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
            raise ConfigError(key="media.rtp.source.ready", reason="must be a text control event")
        event = json.loads(raw_event)
        if not isinstance(event, dict) or event.get("event_type") != SOURCE_READY_EVENT:
            raise ConfigError(key="media.rtp.source.ready", reason="must be received before RTP delivery")
        data = event.get("data")
        if not isinstance(data, dict):
            raise ConfigError(key="media.rtp.source.ready", reason="must contain data")
        if data.get("stream_id") != registration.stream_id or data.get("ssrc") != int(MIC_RTP_SSRC):
            raise ConfigError(key="media.rtp.source.ready", reason="must confirm the registered stream and SSRC")

    async def aclose(self) -> None:
        await self._connection.close()


def _authorization_header(config: ServiceConfig) -> dict[str, str]:
    token = config.trusted_lan_token
    if token is None:
        return {}
    return {"Authorization": f"Bearer {token}"}
