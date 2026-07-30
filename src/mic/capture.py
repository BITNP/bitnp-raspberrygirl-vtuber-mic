"""模块契约说明.

职责: 提供 mic.capture 模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NewType, Protocol

from mic.audio import AudioFrame
from mic.config import ConfigError, ServiceConfig, load_config
from mic.orchestrator_ws import OrchestratorWebSocketBoundary
from mic.portaudio_capture import (
    CaptureDevice,
    PortAudioCaptureSource,
    RawInputStreamFactory,
    open_raw_input_stream,
)

CAPTURE_DEVICE_KEY = "BITNP_CAPTURE_DEVICE"

RTP_STREAM_ID_KEY = "BITNP_MIC_RTP_STREAM_ID"

RTP_TIMESTAMP_KEY = "BITNP_MIC_RTP_TIMESTAMP"


RtpStartTimestamp = NewType("RtpStartTimestamp", int)


class RtpPacketOutput(Protocol):
    """类契约说明.

    职责: 声明 RtpPacketOutput
    协议接口,约束实现方必须提供的行为。
    契约: 方法: write、flush。
    """

    def write(self, packet: bytes) -> int:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `int`。
        """

        ...

    def flush(self) -> None:
        """函数契约说明.

        功能: 执行 flush 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        ...


class ConsoleRtpPacketOutput:
    """类契约说明.

    职责: 定义 ConsoleRtpPacketOutput
    的状态、行为和对外协作边界。
    契约: 方法: write、flush。
    """

    __slots__ = ()

    def write(self, packet: bytes) -> int:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并协调 write。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `int`。
        """

        return sys.stdout.buffer.write(packet)

    def flush(self) -> None:
        """函数契约说明.

        功能: 执行 flush 的同步逻辑,并协调 flush。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        sys.stdout.buffer.flush()


@dataclass(frozen=True, slots=True)
class CaptureRuntimeConfig:
    """类契约说明.

    职责: 保存 CaptureRuntimeConfig
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: service_config、device、stream
    _id、start_timestamp。
    """

    service_config: ServiceConfig

    device: CaptureDevice

    stream_id: str

    start_timestamp: RtpStartTimestamp


class StdoutRtpSink:
    """类契约说明.

    职责: 定义 StdoutRtpSink 的状态、行为和对外协作边界。
    契约: 方法: __init__、receive_rtp_packet、
    receive_audio_frame。
    """

    __slots__ = ("_output",)

    def __init__(self, output: RtpPacketOutput) -> None:
        """函数契约说明.

        功能: 初始化 StdoutRtpSink
        的字段并建立实例不变式。
        参数: self 表示当前实例。 output:
        RtpPacketOutput。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._output = output

    def receive_rtp_packet(self, packet: bytes) -> None:
        """函数契约说明.

        功能: 执行 receive_rtp_packet
        的同步逻辑,并协调 write, flush。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        self._output.write(packet)

        self._output.flush()

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        """函数契约说明.

        功能: 执行 receive_audio_frame
        的同步逻辑,并协调 ConfigError。
        参数: self 表示当前实例。 frame:
        AudioFrame。 必填。
        契约: 同步调用。 返回 `None`。 可能抛出
        ConfigError。
        """

        raise ConfigError(
            key=RTP_STREAM_ID_KEY,
            reason=f"stream must be active before writing frame {frame.metadata.seq}",
        )


def load_capture_runtime_config(
    env: Mapping[str, str] | None = None,
) -> CaptureRuntimeConfig:
    """函数契约说明.

    功能: 执行 load_capture_runtime_config
    的同步逻辑,并协调 _required_value,
    CaptureRuntimeConfig, int,
    ConfigError。
    参数: env: Mapping[str, str] | None。
    可省略。
    契约: 同步调用。 返回 `CaptureRuntimeConfig`。
    可能抛出 ConfigError。
    """

    source = os.environ if env is None else env

    raw_stream_id = _required_value(source, RTP_STREAM_ID_KEY)

    raw_timestamp = _required_value(source, RTP_TIMESTAMP_KEY)

    try:
        timestamp = int(raw_timestamp)

    except ValueError as exc:
        raise ConfigError(key=RTP_TIMESTAMP_KEY, reason="must be an integer") from exc

    if not 0 <= timestamp < 1 << 32:
        raise ConfigError(
            key=RTP_TIMESTAMP_KEY, reason="must be an unsigned 32-bit integer"
        )

    return CaptureRuntimeConfig(
        service_config=load_config(source),
        device=_capture_device(source),
        stream_id=raw_stream_id,
        start_timestamp=RtpStartTimestamp(timestamp),
    )


def run_capture(
    env: Mapping[str, str],
    stream_factory: RawInputStreamFactory,
    output: RtpPacketOutput,
) -> int:
    """函数契约说明.

    功能: 运行流程并协调其依赖步骤。
    参数: env: Mapping[str, str]。 必填。
    stream_factory:
    RawInputStreamFactory。 必填。 output:
    RtpPacketOutput。 必填。
    契约: 同步调用。 返回 `int`。
    """

    config = load_capture_runtime_config(env)

    boundary = OrchestratorWebSocketBoundary(config.service_config)

    boundary.start_rtp_stream(config.stream_id, config.start_timestamp)

    frame = PortAudioCaptureSource(
        device=config.device, stream_factory=stream_factory
    ).capture_and_send(boundary, StdoutRtpSink(output))

    return 0 if frame is not None else 1


def main() -> int:
    """函数契约说明.

    功能: 执行命令行或服务入口流程并返回进程级结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `int`。
    """

    return run_capture(os.environ, open_raw_input_stream, ConsoleRtpPacketOutput())


def _required_value(env: Mapping[str, str], key: str) -> str:
    """函数契约说明.

    功能: 执行 _required_value 的同步逻辑,并协调
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
