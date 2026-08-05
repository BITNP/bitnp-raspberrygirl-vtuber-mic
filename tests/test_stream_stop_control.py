from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mic.config import OrchestratorWsUrl, ServiceConfig, TrustedLanToken
from mic.stream_control import (
    AsrResult,
    ControlContext,
    VoiceEvidence,
    WebsocketsControlConnector,
    WebSocketStreamingControl,
)


@dataclass(slots=True)
class _Connection:
    messages: list[str]
    sent: list[str] = field(default_factory=list)

    async def recv(self) -> str:
        return self.messages.pop(0)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        return


@dataclass(slots=True)
class _ControlConnector:
    connection: _Connection
    ssl_context: ssl.SSLContext | None = None
    headers: dict[str, str] | None = None

    async def connect(self, url: str, headers: dict[str, str], ssl_context: ssl.SSLContext | None) -> _Connection:
        assert url == "wss://orchestrator.example.test/control"
        self.headers = headers
        self.ssl_context = ssl_context
        return self.connection


@pytest.fixture
def ca_path(tmp_path: Path) -> Path:
    certificate = ssl.create_default_context().get_ca_certs(binary_form=True)[0]
    path = tmp_path / "ca.pem"
    _ = path.write_text(ssl.DER_cert_to_PEM_cert(certificate), encoding="ascii")
    return path


def test_websocket_control_only_sends_mic_input_and_asr_events() -> None:
    connection = _Connection(
        messages=[
            json.dumps(
                {
                    "event_type": "mic.input.ready",
                    "source": "orchestrator",
                    "session_id": "s-1",
                    "data": {"stream_id": "mic-1", "input_epoch": 7},
                }
            )
        ]
    )
    control = WebSocketStreamingControl(connection, ControlContext("trace-1", "s-1"))
    result = AsrResult("mic-1", "segment-1", 1, 321, 0, "你好", 10, 0.9)

    async def send_events() -> None:
        await control.register_input("mic-1")
        await control.send_asr_partial(result, sequence=1)
        await control.send_asr_final(result, sequence=2)
        await control.send_voice_evidence(
            VoiceEvidence(
                "mic-1", 7, 1, 321, "camplusplus-onnx-v1", (0.25, -0.5), 20, 0.9
            ),
            sequence=3,
        )

    asyncio.run(send_events())
    events = [json.loads(message) for message in connection.sent]
    assert [event["event_type"] for event in events] == [
        "mic.input.register", "asr.partial", "asr.final", "voice.evidence"
    ]
    assert events[0]["data"] == {"stream_id": "mic-1"}
    assert events[3]["data"]["input_epoch"] == 7
    assert all("rtp_endpoint" not in event["data"] for event in events)


def test_websocket_control_open_passes_verified_ca_context_and_bearer_header_to_connector(ca_path: Path) -> None:
    connector = _ControlConnector(_Connection(messages=[]))
    config = ServiceConfig(
        orchestrator_ws_url=OrchestratorWsUrl("wss://orchestrator.example.test/control"),
        trusted_lan_token=TrustedLanToken("trusted-token"),
        tls_ca_path=ca_path,
    )
    asyncio.run(WebSocketStreamingControl.open(config, ControlContext("trace-001", "session-001"), connector=connector))
    assert isinstance(connector.ssl_context, ssl.SSLContext)
    assert connector.ssl_context.check_hostname is True
    assert connector.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert connector.headers == {"Authorization": "Bearer trusted-token"}


def test_websockets_control_connector_passes_context_to_wss_connect(monkeypatch: pytest.MonkeyPatch, ca_path: Path) -> None:
    connection = _Connection(messages=[])
    captured_context: ssl.SSLContext | None = None
    captured_headers: dict[str, str] | None = None

    async def open_connection(url: str, *, additional_headers: dict[str, str], ssl: ssl.SSLContext) -> _Connection:
        nonlocal captured_context, captured_headers
        assert url == "wss://orchestrator.example.test/control"
        captured_context, captured_headers = ssl, additional_headers
        return connection

    monkeypatch.setattr("mic.stream_control.connect", open_connection)
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(ca_path))
    opened = asyncio.run(WebsocketsControlConnector().connect("wss://orchestrator.example.test/control", {"Authorization": "Bearer trusted-token"}, context))
    assert opened is connection
    assert captured_context is context
    assert captured_headers == {"Authorization": "Bearer trusted-token"}


def test_websockets_control_connector_omits_ssl_for_ws_connect(monkeypatch: pytest.MonkeyPatch, ca_path: Path) -> None:
    connection = _Connection(messages=[])
    captured_headers: dict[str, str] | None = None

    async def open_connection(url: str, *, additional_headers: dict[str, str]) -> _Connection:
        nonlocal captured_headers
        assert url == "ws://127.0.0.1/control"
        captured_headers = additional_headers
        return connection

    monkeypatch.setattr("mic.stream_control.connect", open_connection)
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(ca_path))
    opened = asyncio.run(WebsocketsControlConnector().connect("ws://127.0.0.1/control", {}, context))
    assert opened is connection
    assert captured_headers == {}
