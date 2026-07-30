
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from mic.config import ConfigError
from mic.stream_control import ControlContext, WebSocketStreamingControl
from mic.streaming import (
    RtpEndpoint,
    RtpPort,
    SourceRegistration,
    StreamingRuntimeConfig,
    StreamResources,
    StreamRuntime,
)


@dataclass(slots=True)
class _Connection:

    messages: list[str]

    async def recv(self) -> str:

        return self.messages.pop(0)

    async def send(self, message: str) -> None:

        _ = message

    async def close(self) -> None:

        return


@dataclass(slots=True)
class _BlockingCapture:

    entered: asyncio.Event = field(default_factory=asyncio.Event)

    release: asyncio.Event = field(default_factory=asyncio.Event)

    closed: bool = False

    async def open(self) -> None:

        return

    async def read_block(self) -> bytes | None:

        self.entered.set()

        await self.release.wait()

        return b"\x10\x20" * 320

    async def aclose(self) -> None:

        self.closed = True


@dataclass(slots=True)
class _StopControl:

    capture: _BlockingCapture

    closed: bool = False

    async def register_source(self, registration: SourceRegistration) -> None:

        _ = registration

    async def wait_source_ready(self, registration: SourceRegistration) -> None:

        _ = registration

    async def wait_stop(self, registration: SourceRegistration) -> int:

        _ = registration

        await self.capture.entered.wait()

        return 4

    async def aclose(self) -> None:

        self.closed = True


@dataclass(slots=True)
class _Udp:

    sent: list[bytes] = field(default_factory=list)

    closed: bool = False

    async def bind(self, endpoint: RtpEndpoint) -> None:

        _ = endpoint

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:

        _ = endpoint

        self.sent.append(packet)

    async def aclose(self) -> None:

        self.closed = True


def test_websocket_control_accepts_only_current_orchestrator_flush_epoch() -> None:

    asyncio.run(_flush_epoch_proof())


def test_websocket_control_ignores_sound_flush_before_mic_stop() -> None:

    asyncio.run(_flush_is_not_mic_stop_proof())


def test_stream_runtime_gates_a_pending_capture_before_stop_cancels_it() -> None:

    asyncio.run(_stop_gate_proof())


def test_websocket_control_rejects_malformed_or_foreign_stop() -> None:

    asyncio.run(_malformed_stop_proof())


def test_websocket_control_rejects_duplicate_and_lower_stop_epochs() -> None:

    asyncio.run(_stale_epoch_proof())


async def _flush_epoch_proof() -> None:
    # Given: an authenticated WSS control connection with a current Mic stop envelope.


    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(messages=[_stop(stream_id="stream-001", epoch=4)]),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic receives the Orchestrator's current-stream stop.

    epoch = await control.wait_stop(registration)

    # Then: the exact epoch is admitted for immediate local output gating.

    assert epoch == 4


async def _flush_is_not_mic_stop_proof() -> None:
    # Given: Sound's flush and Mic's authenticated stop are separate controls.


    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _flush(stream_id="stream-001", epoch=4),
                _stop(stream_id="stream-001", epoch=5),
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic waits for its stop after receiving Sound's flush.

    epoch = await control.wait_stop(registration)

    # Then: the flush is ignored and only the Mic stop advances the stop epoch.

    assert epoch == 5


async def _stop_gate_proof() -> None:
    # Given: capture is blocked after opening while authenticated control receives stop epoch four.


    capture = _BlockingCapture()

    control = _StopControl(capture)

    udp = _Udp()

    runtime = StreamRuntime(
        StreamingRuntimeConfig(
            "stream-001",
            96_000,
            RtpEndpoint("127.0.0.1", RtpPort(5004)),
            RtpEndpoint("0.0.0.0", RtpPort(0)),
            None,
        ),
        StreamResources(capture, control, udp),
    )

    # When: the control stop wins while a capture block is still pending.

    await runtime.run()

    # Then: the stop gate prevents a 640-byte frame from reaching UDP before cleanup.

    assert udp.sent == []

    assert capture.closed is True

    assert control.closed is True

    assert udp.closed is True


async def _malformed_stop_proof() -> None:
    # Given: a control envelope not authenticated as an Orchestrator flush for this session.


    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _stop(stream_id="stream-001", epoch=4).replace(
                    '"orchestrator"', '"sound"'
                )
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic receives the foreign control frame after source readiness.

    with pytest.raises(ConfigError, match="authenticated"):
        _ = await control.wait_stop(registration)

    # Then: the source never treats untrusted media control as a local stop.

    malformed = WebSocketStreamingControl(
        _Connection(messages=["{"]), ControlContext("trace-001", "session-001")
    )

    with pytest.raises(ConfigError, match="text control event"):
        _ = await malformed.wait_stop(registration)


async def _stale_epoch_proof() -> None:

    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _stop(stream_id="stream-001", epoch=5),
                _stop(stream_id="stream-001", epoch=5),
                _stop(stream_id="stream-001", epoch=4),
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    assert await control.wait_stop(registration) == 5

    with pytest.raises(ConfigError, match="newer"):
        _ = await control.wait_stop(registration)

    with pytest.raises(ConfigError, match="newer"):
        _ = await control.wait_stop(registration)


def _flush(*, stream_id: str, epoch: int) -> str:

    return _control_event("media.stream.flush", stream_id=stream_id, epoch=epoch)


def _stop(*, stream_id: str, epoch: int) -> str:

    return _control_event("media.rtp.source.stop", stream_id=stream_id, epoch=epoch)


def _control_event(event_type: str, *, stream_id: str, epoch: int) -> str:

    return json.dumps(
        {
            "schema_version": "1.0.0",
            "event_type": event_type,
            "event_id": "flush-001",
            "source": "orchestrator",
            "time": "2026-07-30T00:00:00Z",
            "trace_id": "trace-001",
            "session_id": "session-001",
            "turn_id": "turn-001",
            "segment_id": "segment-001",
            "seq": 4,
            "data": {
                "stream_id": stream_id,
                "cancellation_epoch": epoch,
                "request_id": "flush-request-001",
                "target_generated_ssrc": 0x1234_5678,
            },
        }
    )
