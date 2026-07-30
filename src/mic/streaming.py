"""模块契约说明.

职责: 提供 mic.streaming
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import asyncio  # noqa: ANYIO_OK - asyncio owns the required UDP transport.
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


@dataclass(frozen=True, slots=True)
class RtpEndpoint:
    """类契约说明.

    职责: 保存 RtpEndpoint
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: host、port。
    """

    host: str

    port: RtpPort


@dataclass(frozen=True, slots=True)
class SourceRegistration:
    """类契约说明.

    职责: 保存 SourceRegistration
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream_id、rtp_endpoint。
    """

    stream_id: str

    rtp_endpoint: RtpEndpoint


@dataclass(frozen=True, slots=True)
class StreamingRuntimeConfig:
    """类契约说明.

    职责: 保存 StreamingRuntimeConfig
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream_id、start_timestamp、rt
    p_endpoint、udp_bind_endpoint、max_blo
    cks、service_config。
    """

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
    """类契约说明.

    职责: 保存 UdpSenderStateError
    不可变数据结构,用类型标注表达字段契约。
    契约: 方法: __str__。
    """

    def __str__(self) -> str:
        """函数契约说明.

        功能: 生成面向日志、错误或调试输出的稳定文本表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return "UDP sender must bind before sending"


class BlockCapture(Protocol):
    """类契约说明.

    职责: 声明 BlockCapture
    协议接口,约束实现方必须提供的行为。
    契约: 方法: open、read_block、aclose。
    """

    async def open(self) -> None:
        """函数契约说明.

        功能: 执行 open 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def read_block(self) -> bytes | None:
        """函数契约说明.

        功能: 执行 read_block 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `bytes | None`。
        """

        ...

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        ...


class StreamingControl(Protocol):
    """类契约说明.

    职责: 声明 StreamingControl
    协议接口,约束实现方必须提供的行为。
    契约: 方法: register_source、wait_source_
    ready、wait_stop、aclose。
    """

    async def register_source(self, registration: SourceRegistration) -> None:
        """函数契约说明.

        功能: 执行 register_source
        的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def wait_source_ready(self, registration: SourceRegistration) -> None:
        """函数契约说明.

        功能: 执行 wait_source_ready
        的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def wait_stop(self, registration: SourceRegistration) -> int:
        """函数契约说明.

        功能: 执行 wait_stop 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 返回 `int`。
        """

        ...

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        ...


class UdpPacketSender(Protocol):
    """类契约说明.

    职责: 声明 UdpPacketSender
    协议接口,约束实现方必须提供的行为。
    契约: 方法: bind、send、aclose。
    """

    async def bind(self, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 执行 bind 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 endpoint:
        RtpEndpoint。 必填。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 packet: bytes。
        必填。 endpoint: RtpEndpoint。 必填。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        ...


@dataclass(frozen=True, slots=True)
class StreamResources:
    """类契约说明.

    职责: 保存 StreamResources
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: capture、control、udp。
    """

    capture: BlockCapture

    control: StreamingControl

    udp: UdpPacketSender


class StreamRuntime:
    """类契约说明.

    职责: 定义 StreamRuntime 的状态、行为和对外协作边界。
    契约: 方法:
    __init__、run、_send_capture_blocks。
    """

    __slots__ = ("_config", "_resources")

    def __init__(
        self, config: StreamingRuntimeConfig, resources: StreamResources
    ) -> None:
        """函数契约说明.

        功能: 初始化 StreamRuntime
        的字段并建立实例不变式。
        参数: self 表示当前实例。 config:
        StreamingRuntimeConfig。 必填。
        resources: StreamResources。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._config = config

        self._resources = resources

    async def run(self) -> None:
        """函数契约说明.

        功能: 运行流程并协调其依赖步骤。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        registration = SourceRegistration(
            stream_id=self._config.stream_id,
            rtp_endpoint=self._config.rtp_endpoint,
        )

        await self._resources.udp.bind(self._config.udp_bind_endpoint)

        try:
            await self._resources.control.register_source(registration)

            await self._resources.control.wait_source_ready(registration)

            await self._resources.capture.open()

            await self._send_capture_blocks(registration)

        finally:
            await self._resources.capture.aclose()

            await self._resources.control.aclose()

            await self._resources.udp.aclose()

    async def _send_capture_blocks(self, registration: SourceRegistration) -> None:
        """函数契约说明.

        功能: 执行 _send_capture_blocks
        的异步逻辑,并协调 RtpStream,
        create_task, wait_stop, cancel。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。 可能抛出 ConfigError。
        """

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

                sent_blocks += 1

        finally:
            stop_task.cancel()

            with suppress(asyncio.CancelledError):
                await stop_task


class AsyncioUdpSender:
    """类契约说明.

    职责: 定义 AsyncioUdpSender
    的状态、行为和对外协作边界。
    契约: 方法: __init__、bind、send、aclose。
    """

    __slots__ = ("_transport",)

    def __init__(self) -> None:
        """函数契约说明.

        功能: 初始化 AsyncioUdpSender
        的字段并建立实例不变式。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self._transport: asyncio.DatagramTransport | None = None

    async def bind(self, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 执行 bind 的异步逻辑,并协调
        get_running_loop,
        create_datagram_endpoint, int。
        参数: self 表示当前实例。 endpoint:
        RtpEndpoint。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        loop = asyncio.get_running_loop()

        transport, _protocol = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=(endpoint.host, int(endpoint.port)),
        )

        self._transport = transport

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 packet: bytes。
        必填。 endpoint: RtpEndpoint。 必填。
        契约: 异步调用。 返回 `None`。 可能抛出
        UdpSenderStateError。
        """

        transport = self._transport

        if transport is None:
            raise UdpSenderStateError()

        transport.sendto(packet, (endpoint.host, int(endpoint.port)))

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并协调 close。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        transport = self._transport

        if transport is not None:
            transport.close()

            self._transport = None


def load_streaming_runtime_config(
    env: Mapping[str, str] | None = None,
) -> StreamingRuntimeConfig:
    """函数契约说明.

    功能: 执行 load_streaming_runtime_config
    的同步逻辑,并协调 load_config,
    _enforce_control_security,
    StreamingRuntimeConfig,
    _required_text。
    参数: env: Mapping[str, str] | None。
    可省略。
    契约: 同步调用。 返回
    `StreamingRuntimeConfig`。
    """

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
    """函数契约说明.

    功能: 执行 _enforce_control_security
    的同步逻辑,并协调 urlparse, ConfigError,
    _loopback_ws_allowed, lower。
    参数: config: ServiceConfig。 必填。 env:
    Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `None`。 可能抛出
    ConfigError。
    """

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
    """函数契约说明.

    功能: 执行 _loopback_ws_allowed
    的同步逻辑,并协调 lower, ConfigError, strip,
    get。
    参数: env: Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `bool`。 可能抛出
    ConfigError。
    """

    value = env.get(MIC_ALLOW_LOOPBACK_WS_KEY, "false").strip().lower()

    if value == "true":
        return True

    if value == "false":
        return False

    raise ConfigError(key=MIC_ALLOW_LOOPBACK_WS_KEY, reason="must be true or false")


def _required_text(env: Mapping[str, str], key: str) -> str:
    """函数契约说明.

    功能: 执行 _required_text 的同步逻辑,并协调
    strip, ConfigError, get。
    参数: env: Mapping[str, str]。 必填。 key:
    str。 必填。
    契约: 同步调用。 返回 `str`。 可能抛出
    ConfigError。
    """

    value = env.get(key, "").strip()

    if value == "":
        raise ConfigError(key=key, reason="must be configured")

    return value


def _unsigned_timestamp(env: Mapping[str, str]) -> int:
    """函数契约说明.

    功能: 执行 _unsigned_timestamp 的同步逻辑,并协调
    _required_text, int, ConfigError,
    isdecimal。
    参数: env: Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出
    ConfigError。
    """

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
    """函数契约说明.

    功能: 执行 _port 的同步逻辑,并协调 get, int,
    RtpPort, ConfigError。
    参数: env: Mapping[str, str]。 必填。 key:
    str。 必填。 default: str | None。 可省略。
    allow_zero: bool。 可省略。
    契约: 同步调用。 返回 `RtpPort`。 可能抛出
    ConfigError。
    """

    value = env.get(key, default)

    if value is None or not value.strip().isdecimal():
        raise ConfigError(key=key, reason="must be an integer port")

    port = int(value)

    if port > 65_535 or (port == 0 and not allow_zero):
        raise ConfigError(key=key, reason="must be between 1 and 65535")

    return RtpPort(port)


def _max_blocks(env: Mapping[str, str]) -> int | None:
    """函数契约说明.

    功能: 执行 _max_blocks 的同步逻辑,并协调 strip,
    int, ConfigError, get。
    参数: env: Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `int | None`。 可能抛出
    ConfigError。
    """

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
    """函数契约说明.

    功能: 执行 _capture_device 的同步逻辑,并协调
    strip, isdecimal, int, get。
    参数: env: Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `CaptureDevice`。
    """

    value = env.get(CAPTURE_DEVICE_KEY, "").strip()

    if value == "" or value == "default":
        return None

    if value.isdecimal():
        return int(value)

    return value
