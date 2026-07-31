import asyncio  # noqa: ANYIO_OK - asyncio owns the required UDP transport.
import logging
import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Final, NewType, Protocol
from urllib.parse import urlparse

from mic.config import ConfigError, ServiceConfig, load_config
from mic.portaudio_capture import CaptureDevice
from mic.rtp import (
    L16_FRAME_BYTES,
    MIC_RTP_SSRC,
    RtpSequence,
    RtpStream,
    RtpTimestamp,
    packetize_l16_pcm16le,
)

RtpPort = NewType("RtpPort", int)


ORCHESTRATOR_RTP_HOST_KEY: Final = "ORCHESTRATOR_RTP_HOST"

ORCHESTRATOR_RTP_PORT_KEY: Final = "ORCHESTRATOR_RTP_PORT"

MIC_RTP_BIND_HOST_KEY: Final = "MIC_RTP_BIND_HOST"

MIC_RTP_BIND_PORT_KEY: Final = "MIC_RTP_BIND_PORT"

MIC_ALLOW_LOOPBACK_WS_KEY: Final = "MIC_ALLOW_LOOPBACK_WS"

MAX_CAPTURE_BLOCKS_KEY: Final = "MIC_MAX_CAPTURE_BLOCKS"

RTP_STREAM_ID_KEY: Final = "BITNP_MIC_RTP_STREAM_ID"

RTP_TIMESTAMP_KEY: Final = "BITNP_MIC_RTP_TIMESTAMP"

CAPTURE_DEVICE_KEY: Final = "BITNP_CAPTURE_DEVICE"

TRACE_ID_KEY: Final = "BITNP_TRACE_ID"

SESSION_ID_KEY: Final = "BITNP_SESSION_ID"

LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RtpEndpoint:
    host: str

    port: RtpPort


@dataclass(frozen=True, slots=True)
class SourceRegistration:
    stream_id: str

    rtp_endpoint: RtpEndpoint


@dataclass(frozen=True, slots=True)
class StreamingRuntimeConfig:
    stream_id: str

    start_timestamp: int

    rtp_endpoint: RtpEndpoint

    udp_bind_endpoint: RtpEndpoint

    max_blocks: int | None

    service_config: ServiceConfig | None = None

    device: CaptureDevice = None

    trace_id: str = "mic-stream"

    session_id: str = "mic-stream"


@dataclass(frozen=True, slots=True)
class UdpSenderStateError(RuntimeError):
    def __str__(self) -> str:

        return "UDP sender must bind before sending"


class BlockCapture(Protocol):
    async def open(self) -> None: ...

    async def read_block(self) -> bytes | None: ...

    async def aclose(self) -> None: ...


class StreamingControl(Protocol):
    async def register_source(self, registration: SourceRegistration) -> None: ...

    async def wait_source_ready(self, registration: SourceRegistration) -> None: ...

    async def wait_stop(self, registration: SourceRegistration) -> int: ...

    async def aclose(self) -> None: ...


class UdpPacketSender(Protocol):
    async def bind(self, endpoint: RtpEndpoint) -> None: ...

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StreamResources:
    capture: BlockCapture

    control: StreamingControl

    udp: UdpPacketSender


class StreamRuntime:
    __slots__ = ("_config", "_resources")

    def __init__(
        self, config: StreamingRuntimeConfig, resources: StreamResources
    ) -> None:

        self._config = config

        self._resources = resources

    async def run(self) -> None:

        registration = SourceRegistration(
            stream_id=self._config.stream_id,
            rtp_endpoint=self._config.rtp_endpoint,
        )

        await self._resources.udp.bind(self._config.udp_bind_endpoint)
        _LOGGER.debug(
            "mic_rtp_bind host=%s port=%d",
            self._config.udp_bind_endpoint.host,
            self._config.udp_bind_endpoint.port,
        )

        try:
            await self._resources.control.register_source(registration)
            _LOGGER.debug(
                "mic_control_sent event=media.rtp.source.register stream=%s rtp_host=%s rtp_port=%d",
                registration.stream_id,
                registration.rtp_endpoint.host,
                registration.rtp_endpoint.port,
            )

            await self._resources.control.wait_source_ready(registration)
            _LOGGER.debug(
                "mic_control_received event=media.rtp.source.ready stream=%s",
                registration.stream_id,
            )

            await self._resources.capture.open()

            await self._send_capture_blocks(registration)

        finally:
            await self._resources.capture.aclose()

            await self._resources.control.aclose()

            await self._resources.udp.aclose()

    async def _send_capture_blocks(self, registration: SourceRegistration) -> None:

        stream = RtpStream(
            stream_id=self._config.stream_id,
            sequence=RtpSequence(0),
            timestamp=RtpTimestamp(self._config.start_timestamp),
            ssrc=MIC_RTP_SSRC,
        )

        sent_blocks = 0

        stop_task = asyncio.create_task(self._resources.control.wait_stop(registration))

        try:
            while (
                self._config.max_blocks is None or sent_blocks < self._config.max_blocks
            ):
                capture_task = asyncio.create_task(self._resources.capture.read_block())

                done, _ = await asyncio.wait(
                    (capture_task, stop_task), return_when=asyncio.FIRST_COMPLETED
                )

                if stop_task in done:
                    _ = stop_task.result()

                    capture_task.cancel()

                    with suppress(asyncio.CancelledError):
                        await capture_task

                    return

                block = capture_task.result()

                if block is None:
                    return

                if len(block) != L16_FRAME_BYTES:
                    raise ConfigError(
                        key="capture.block",
                        reason="must contain exactly 640 PCM16 bytes",
                    )

                packet, stream = packetize_l16_pcm16le(block, stream)

                await self._resources.udp.send(packet, self._config.rtp_endpoint)
                _LOGGER.debug(
                    "mic_rtp_sent stream=%s packet_bytes=%d",
                    registration.stream_id,
                    len(packet),
                )

                sent_blocks += 1

        finally:
            stop_task.cancel()

            with suppress(asyncio.CancelledError):
                await stop_task


class AsyncioUdpSender:
    __slots__ = ("_transport",)

    def __init__(self) -> None:

        self._transport: asyncio.DatagramTransport | None = None

    async def bind(self, endpoint: RtpEndpoint) -> None:

        loop = asyncio.get_running_loop()

        transport, _protocol = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=(endpoint.host, int(endpoint.port)),
        )

        self._transport = transport

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:

        transport = self._transport

        if transport is None:
            raise UdpSenderStateError()

        transport.sendto(packet, (endpoint.host, int(endpoint.port)))

    async def aclose(self) -> None:

        transport = self._transport

        if transport is not None:
            transport.close()

            self._transport = None


def load_streaming_runtime_config(
    env: Mapping[str, str] | None = None,
) -> StreamingRuntimeConfig:

    source = os.environ if env is None else env

    service_config = load_config(source)

    _enforce_control_security(service_config, source)

    return StreamingRuntimeConfig(
        stream_id=_required_text(source, RTP_STREAM_ID_KEY),
        start_timestamp=_unsigned_timestamp(source),
        rtp_endpoint=RtpEndpoint(
            host=_required_text(source, ORCHESTRATOR_RTP_HOST_KEY),
            port=_port(source, ORCHESTRATOR_RTP_PORT_KEY),
        ),
        udp_bind_endpoint=RtpEndpoint(
            host=source.get(MIC_RTP_BIND_HOST_KEY, "0.0.0.0").strip(),
            port=_port(source, MIC_RTP_BIND_PORT_KEY, default="0", allow_zero=True),
        ),
        max_blocks=_max_blocks(source),
        service_config=service_config,
        device=_capture_device(source),
        trace_id=_required_text(source, TRACE_ID_KEY),
        session_id=_required_text(source, SESSION_ID_KEY),
    )


def _enforce_control_security(config: ServiceConfig, env: Mapping[str, str]) -> None:

    parsed = urlparse(config.orchestrator_ws_url)

    if parsed.scheme == "wss":
        if config.trusted_lan_token is None:
            raise ConfigError(
                key="TRUSTED_LAN_TOKEN", reason="must be configured for WSS control"
            )

        return

    if _loopback_ws_allowed(env) and (parsed.hostname or "").lower() in LOOPBACK_HOSTS:
        return

    raise ConfigError(
        key="ORCHESTRATOR_WS_URL",
        reason="must use WSS outside explicit loopback test mode",
    )


def _loopback_ws_allowed(env: Mapping[str, str]) -> bool:

    value = env.get(MIC_ALLOW_LOOPBACK_WS_KEY, "false").strip().lower()

    if value == "true":
        return True

    if value == "false":
        return False

    raise ConfigError(key=MIC_ALLOW_LOOPBACK_WS_KEY, reason="must be true or false")


def _required_text(env: Mapping[str, str], key: str) -> str:

    value = env.get(key, "").strip()

    if value == "":
        raise ConfigError(key=key, reason="must be configured")

    return value


def _unsigned_timestamp(env: Mapping[str, str]) -> int:

    value = _required_text(env, RTP_TIMESTAMP_KEY)

    if not value.isdecimal() or int(value) >= 1 << 32:
        raise ConfigError(
            key=RTP_TIMESTAMP_KEY, reason="must be an unsigned 32-bit integer"
        )

    return int(value)


def _port(
    env: Mapping[str, str],
    key: str,
    *,
    default: str | None = None,
    allow_zero: bool = False,
) -> RtpPort:

    value = env.get(key, default)

    if value is None or not value.strip().isdecimal():
        raise ConfigError(key=key, reason="must be an integer port")

    port = int(value)

    if port > 65_535 or (port == 0 and not allow_zero):
        raise ConfigError(key=key, reason="must be between 1 and 65535")

    return RtpPort(port)


def _max_blocks(env: Mapping[str, str]) -> int | None:

    value = env.get(MAX_CAPTURE_BLOCKS_KEY, "").strip()

    if value == "":
        return None

    if not value.isdecimal() or int(value) == 0:
        raise ConfigError(
            key=MAX_CAPTURE_BLOCKS_KEY,
            reason="must be a positive integer when configured",
        )

    return int(value)


def _capture_device(env: Mapping[str, str]) -> CaptureDevice:

    value = env.get(CAPTURE_DEVICE_KEY, "").strip()

    if value == "" or value == "default":
        return None

    if value.isdecimal():
        return int(value)

    return value
