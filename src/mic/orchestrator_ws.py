"""模块契约说明.

职责: 提供 mic.orchestrator_ws
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from typing import Final, assert_never

from mic.audio import AudioFrame, AudioRtpSink
from mic.config import OrchestratorWsUrl, ServiceConfig
from mic.rtp import (
    RtpPacket,
    RtpPacketRejected,
    RtpSequence,
    RtpSsrc,
    RtpStream,
    RtpTimestamp,
    packetize_l16_pcm16le,
    parse_l16_rtp_packet,
)

MIC_RTP_SSRC: Final = RtpSsrc(0x4D494331)


class OrchestratorWebSocketBoundary:
    """类契约说明.

    职责: 定义 OrchestratorWebSocketBoundary
    的状态、行为和对外协作边界。
    契约: 方法: __init__、target_url、describe
    _placeholder、start_rtp_stream、send_a
    udio_frame、deliver_rtp_packet。
    """

    __slots__ = ("_stream", "config")

    def __init__(self, config: ServiceConfig) -> None:
        """函数契约说明.

        功能: 初始化
        OrchestratorWebSocketBoundary
        的字段并建立实例不变式。
        参数: self 表示当前实例。 config:
        ServiceConfig。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.config = config

        self._stream: RtpStream | None = None

    def target_url(self) -> OrchestratorWsUrl:
        """函数契约说明.

        功能: 执行 target_url 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回
        `OrchestratorWsUrl`。
        """

        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        """函数契约说明.

        功能: 执行 describe_placeholder
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return "mic WebSocket boundary placeholder targets Orchestrator only"

    def start_rtp_stream(self, stream_id: str, start_rtp_timestamp: int) -> None:
        """函数契约说明.

        功能: 执行 start_rtp_stream
        的同步逻辑,并协调 RtpStream,
        RtpSequence, RtpTimestamp。
        参数: self 表示当前实例。 stream_id: str。
        必填。 start_rtp_timestamp: int。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        self._stream = RtpStream(
            stream_id=stream_id,
            sequence=RtpSequence(0),
            timestamp=RtpTimestamp(start_rtp_timestamp),
            ssrc=MIC_RTP_SSRC,
        )

    def send_audio_frame(self, sink: AudioRtpSink, frame: AudioFrame) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 sink:
        AudioRtpSink。 必填。 frame:
        AudioFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        stream = self._stream

        if stream is None:
            sink.receive_audio_frame(frame)

            return

        packet, self._stream = packetize_l16_pcm16le(frame.payload, stream)

        self.deliver_rtp_packet(sink, packet)

    def deliver_rtp_packet(self, sink: AudioRtpSink, packet: bytes) -> bool:
        """函数契约说明.

        功能: 执行 deliver_rtp_packet
        的同步逻辑,并协调 parse_l16_rtp_packet,
        receive_rtp_packet,
        assert_never。
        参数: self 表示当前实例。 sink:
        AudioRtpSink。 必填。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        parsed = parse_l16_rtp_packet(packet)

        match parsed:
            case RtpPacketRejected():
                return False

            case RtpPacket():
                sink.receive_rtp_packet(packet)

                return True

            case unreachable:
                assert_never(unreachable)
