from __future__ import annotations

import asyncio
import socket
import ssl
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from websockets.asyncio.server import ServerConnection, serve

from mic.config import load_config
from mic.stream_control import ControlContext, WebSocketStreamingControl


def test_mic_control_accepts_private_ca_and_rejects_default_or_wrong_hostname(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    asyncio.run(_private_ca_proof(tmp_path))


async def _private_ca_proof(tmp_path: Path) -> None:
    # Given: an authenticated local WSS control listener signed by a temporary CA.
    certificates = _certificates(tmp_path)
    authorizations: list[str | None] = []

    async def receive(connection: ServerConnection) -> None:
        request = connection.request
        assert request is not None
        authorizations.append(request.headers.get("Authorization"))
        await connection.wait_closed()

    server = await serve(receive, "localhost", 0, ssl=_server_context(certificates))
    port = _port(server.sockets)
    default_config = load_config(
        {
            "ORCHESTRATOR_WS_URL": f"wss://localhost:{port}/control",
            "TRUSTED_LAN_TOKEN": "token",
        }
    )
    trusted_config = load_config(
        {
            "ORCHESTRATOR_WS_URL": f"wss://localhost:{port}/control",
            "TRUSTED_LAN_TOKEN": "token",
            "ORCHESTRATOR_TLS_CA_PATH": str(certificates.ca_path),
        }
    )
    unrelated_ca_config = load_config(
        {
            "ORCHESTRATOR_WS_URL": f"wss://localhost:{port}/control",
            "TRUSTED_LAN_TOKEN": "token",
            "ORCHESTRATOR_TLS_CA_PATH": str(certificates.unrelated_ca_path),
        }
    )
    mismatched_config = load_config(
        {
            "ORCHESTRATOR_WS_URL": f"wss://127.0.0.1:{port}/control",
            "TRUSTED_LAN_TOKEN": "token",
            "ORCHESTRATOR_TLS_CA_PATH": str(certificates.ca_path),
        }
    )

    try:
        # When: default trust attempts the private-CA listener before any protocol work.
        with pytest.raises(ssl.SSLCertVerificationError):
            _ = await WebSocketStreamingControl.open(
                default_config, ControlContext("trace-default", "session-default")
            )

        # Then: the TLS failure reaches no authenticated control handler.
        assert authorizations == []

        with pytest.raises(ssl.SSLCertVerificationError):
            _ = await WebSocketStreamingControl.open(
                unrelated_ca_config,
                ControlContext("trace-unrelated", "session-unrelated"),
            )

        assert authorizations == []

        # When: the environment-configured CA path opens the same listener.
        control = await WebSocketStreamingControl.open(
            trusted_config, ControlContext("trace-trusted", "session-trusted")
        )
        await control.aclose()

        # Then: the unchanged bearer header arrives only after trusted TLS succeeds.
        assert authorizations == ["Bearer token"]

        # When: the trusted CA is used with a hostname absent from the certificate.
        with pytest.raises(ssl.SSLCertVerificationError):
            _ = await WebSocketStreamingControl.open(
                mismatched_config,
                ControlContext("trace-mismatched", "session-mismatched"),
            )

        # Then: hostname verification blocks the handshake before authorization.
        assert authorizations == ["Bearer token"]
    finally:
        server.close()
        await server.wait_closed()


@dataclass(frozen=True, slots=True)
class _Certificates:
    ca_path: Path
    unrelated_ca_path: Path
    certificate_path: Path
    key_path: Path


def _certificates(directory: Path) -> _Certificates:
    ca_path = directory / "ca.pem"
    ca_key_path = directory / "ca.key"
    unrelated_ca_path = directory / "unrelated-ca.pem"
    unrelated_ca_key_path = directory / "unrelated-ca.key"
    certificate_path = directory / "server.pem"
    key_path = directory / "server.key"
    request_path = directory / "server.csr"

    _run_openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(ca_key_path),
        "-out",
        str(ca_path),
        "-subj",
        "/CN=temporary-test-ca",
        "-days",
        "1",
    )
    _run_openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(unrelated_ca_key_path),
        "-out",
        str(unrelated_ca_path),
        "-subj",
        "/CN=unrelated-test-ca",
        "-days",
        "1",
    )
    _run_openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(request_path),
        "-subj",
        "/CN=localhost",
    )
    _run_openssl(
        "x509",
        "-req",
        "-in",
        str(request_path),
        "-CA",
        str(ca_path),
        "-CAkey",
        str(ca_key_path),
        "-CAcreateserial",
        "-out",
        str(certificate_path),
        "-days",
        "1",
        "-extfile",
        "/dev/stdin",
        input="subjectAltName=DNS:localhost\n",
    )

    return _Certificates(ca_path, unrelated_ca_path, certificate_path, key_path)


def _run_openssl(*arguments: str, input: str | None = None) -> None:
    _ = subprocess.run(
        ["openssl", *arguments],
        check=True,
        input=input,
        text=True,
        capture_output=True,
    )


def _server_context(certificates: _Certificates) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates.certificate_path, certificates.key_path)
    return context


def _port(sockets: tuple[socket.socket, ...]) -> int:
    socket = sockets[0]
    address = cast(tuple[str, int], socket.getsockname())
    assert isinstance(address, tuple)
    port = address[1]
    assert isinstance(port, int)
    return port
