import asyncio  # noqa: ANYIO_OK - exercises asyncio cancellation and UDP seams.
from dataclasses import dataclass, field

import pytest

from mic.config import ConfigError
from mic.streaming import (
    RtpEndpoint,
    RtpPort,
    SourceRegistration,
    StreamingRuntimeConfig,
    StreamResources,
    StreamRuntime,
    load_streaming_runtime_config,
)


@dataclass(slots=True)  # noqa: MUTABLE_OK - records fake capture calls.
class FakeCapture:
    blocks: list[bytes | None]
    reads: int = 0
    opened: bool = False
    closed: bool = False

    async def open(self) -> None:
        self.opened = True

    async def read_block(self) -> bytes | None:
        self.reads += 1
        return self.blocks.pop(0)

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)  # noqa: MUTABLE_OK - blocks and releases cancellation deterministically.
class BlockingCapture:
    entered_read: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False
    reads: int = 0

    async def open(self) -> None:
        return None

    async def read_block(self) -> bytes | None:
        self.reads += 1
        self.entered_read.set()
        await self.release.wait()
        return None

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)  # noqa: MUTABLE_OK - records fake UDP datagrams.
class FakeUdp:
    bound: RtpEndpoint | None = None
    sent: list[tuple[bytes, RtpEndpoint]] = field(default_factory=list)
    closed: bool = False

    async def bind(self, endpoint: RtpEndpoint) -> None:
        self.bound = endpoint

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:
        self.sent.append((packet, endpoint))

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)  # noqa: MUTABLE_OK - records fake control lifecycle.
class FakeControl:
    capture: FakeCapture | BlockingCapture
    udp: FakeUdp
    registrations: list[SourceRegistration] = field(default_factory=list)
    closed: bool = False

    async def register_source(self, registration: SourceRegistration) -> None:
        self.registrations.append(registration)

    async def wait_source_ready(self, registration: SourceRegistration) -> None:
        assert self.capture.reads == 0
        assert self.udp.sent == []
        assert self.registrations == [registration]

    async def wait_stop(self, registration: SourceRegistration) -> int:
        _ = registration
        return await asyncio.Future[int]()

    async def aclose(self) -> None:
        self.closed = True


def _config(*, max_blocks: int | None = None) -> StreamingRuntimeConfig:
    return StreamingRuntimeConfig(
        stream_id="mic-primary",
        start_timestamp=96_000,
        rtp_endpoint=RtpEndpoint(host="orchestrator.example.test", port=RtpPort(5004)),
        udp_bind_endpoint=RtpEndpoint(host="0.0.0.0", port=RtpPort(0)),
        max_blocks=max_blocks,
    )


def test_runtime_waits_for_source_ready_before_first_rtp_packet() -> None:
    # Given: an unready route and one complete PortAudio-sized capture block.
    capture = FakeCapture(blocks=[b"\x01\x02" * 320, None])
    udp = FakeUdp()
    control = FakeControl(capture=capture, udp=udp)

    # When: the stream runtime performs its control-confirmed startup.
    asyncio.run(StreamRuntime(_config(max_blocks=1), StreamResources(capture, control, udp)).run())

    # Then: registration happened before the first RTP packet and route data is exact.
    assert control.registrations == [
        SourceRegistration(
            stream_id="mic-primary",
            rtp_endpoint=RtpEndpoint(host="orchestrator.example.test", port=RtpPort(5004)),
        )
    ]
    assert len(udp.sent) == 1


def test_runtime_packetizes_one_rtp_frame_per_capture_block() -> None:
    # Given: two complete, distinguishable 320-sample capture blocks.
    first = b"\x10\x20" * 320
    second = b"\x30\x40" * 320
    capture = FakeCapture(blocks=[first, second, None])
    udp = FakeUdp()
    control = FakeControl(capture=capture, udp=udp)

    # When: the bounded runtime sends two blocks.
    asyncio.run(StreamRuntime(_config(max_blocks=2), StreamResources(capture, control, udp)).run())

    # Then: each block maps to exactly one existing V2/PT96/L16 RTP frame.
    assert [packet for packet, _endpoint in udp.sent] == [
        b"\x80\x60\x00\x00\x00\x01\x77\x00MIC1" + b"\x20\x10" * 320,
        b"\x80\x60\x00\x01\x00\x01\x78\x40MIC1" + b"\x40\x30" * 320,
    ]


@pytest.mark.parametrize("block", [b"\x10\x20" * 319, b"\x10\x20" * 321])
def test_runtime_rejects_capture_blocks_that_are_not_exactly_20ms(block: bytes) -> None:
    capture = FakeCapture(blocks=[block])
    udp = FakeUdp()
    control = FakeControl(capture=capture, udp=udp)

    with pytest.raises(ConfigError, match="640"):
        asyncio.run(StreamRuntime(_config(max_blocks=1), StreamResources(capture, control, udp)).run())

    assert udp.sent == []


def test_runtime_streams_until_capture_ends_when_block_limit_is_unset() -> None:
    # Given: continuous mode and two capture blocks followed by an end-of-capture signal.
    capture = FakeCapture(blocks=[b"\x00\x01" * 320, b"\x02\x03" * 320, None])
    udp = FakeUdp()
    control = FakeControl(capture=capture, udp=udp)

    # When: the runtime has no configured block limit.
    asyncio.run(StreamRuntime(_config(), StreamResources(capture, control, udp)).run())

    # Then: it sends both blocks and stops only after capture ends.
    assert len(udp.sent) == 2
    assert capture.reads == 3


def test_runtime_cancellation_closes_capture_control_and_udp() -> None:
    # Given: a continuous capture blocked in its next read.
    capture = BlockingCapture()
    udp = FakeUdp()
    control = FakeControl(capture=capture, udp=udp)

    async def cancel_running_stream() -> None:
        task = asyncio.create_task(StreamRuntime(_config(), StreamResources(capture, control, udp)).run())
        await capture.entered_read.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # When: the runtime task is cancelled.
    asyncio.run(cancel_running_stream())

    # Then: every owned resource is deterministically released.
    assert capture.closed is True
    assert control.closed is True
    assert udp.closed is True


def test_stream_config_requires_wss_except_for_explicit_loopback_ws() -> None:
    # Given: a deployable route with all required Mic stream configuration.
    base_environment = {
        "ORCHESTRATOR_WS_URL": "ws://127.0.0.1:8765/control",
        "ORCHESTRATOR_RTP_HOST": "127.0.0.1",
        "ORCHESTRATOR_RTP_PORT": "5004",
        "BITNP_MIC_RTP_STREAM_ID": "mic-primary",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
        "BITNP_TRACE_ID": "trace-mic-001",
        "BITNP_SESSION_ID": "session-mic-001",
    }

    # When / Then: unsecured WS is rejected until the loopback-only policy is explicit.
    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        load_streaming_runtime_config(base_environment)
    config = load_streaming_runtime_config({**base_environment, "MIC_ALLOW_LOOPBACK_WS": "true"})
    assert config.rtp_endpoint == RtpEndpoint(host="127.0.0.1", port=RtpPort(5004))
