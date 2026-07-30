"""模块契约说明.

职责: 提供 mic.rtp 模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass
from typing import Final, NewType

RtpSequence = NewType("RtpSequence", int)

RtpTimestamp = NewType("RtpTimestamp", int)

RtpSsrc = NewType("RtpSsrc", int)


RTP_VERSION_2_HEADER: Final = 0x80

L16_PAYLOAD_TYPE: Final = 96

RTP_HEADER_SIZE: Final = 12

RTP_SAMPLES_PER_20MS_FRAME: Final = 320

L16_FRAME_BYTES: Final = RTP_SAMPLES_PER_20MS_FRAME * 2


@dataclass(frozen=True, slots=True)
class RtpStream:
    """类契约说明.

    职责: 保存 RtpStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    stream_id、sequence、timestamp、ssrc。
    """

    stream_id: str

    sequence: RtpSequence

    timestamp: RtpTimestamp

    ssrc: RtpSsrc


@dataclass(frozen=True, slots=True)
class RtpPacket:
    """类契约说明.

    职责: 保存 RtpPacket
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    sequence、timestamp、ssrc、payload。
    """

    sequence: RtpSequence

    timestamp: RtpTimestamp

    ssrc: RtpSsrc

    payload: bytes


@dataclass(frozen=True, slots=True)
class RtpPacketRejected:
    """类契约说明.

    职责: 保存 RtpPacketRejected
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: reason。
    """

    reason: str


def packetize_l16_pcm16le(payload: bytes, stream: RtpStream) -> tuple[bytes, RtpStream]:
    """函数契约说明.

    功能: 执行 packetize_l16_pcm16le
    的同步逻辑,并协调 join, RtpStream, bytes,
    to_bytes。
    参数: payload: bytes。 必填。 stream:
    RtpStream。 必填。
    契约: 同步调用。 返回 `tuple[bytes,
    RtpStream]`。
    """

    l16_payload = b"".join(
        payload[index : index + 2][::-1] for index in range(0, len(payload), 2)
    )

    packet = b"".join(
        (
            bytes((RTP_VERSION_2_HEADER, L16_PAYLOAD_TYPE)),
            int(stream.sequence).to_bytes(2, byteorder="big"),
            int(stream.timestamp).to_bytes(4, byteorder="big"),
            int(stream.ssrc).to_bytes(4, byteorder="big"),
            l16_payload,
        )
    )

    next_stream = RtpStream(
        stream_id=stream.stream_id,
        sequence=RtpSequence((int(stream.sequence) + 1) % (1 << 16)),
        timestamp=RtpTimestamp(
            (int(stream.timestamp) + RTP_SAMPLES_PER_20MS_FRAME) % (1 << 32)
        ),
        ssrc=stream.ssrc,
    )

    return packet, next_stream


def parse_l16_rtp_packet(packet: bytes) -> RtpPacket | RtpPacketRejected:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: packet: bytes。 必填。
    契约: 同步调用。 返回 `RtpPacket |
    RtpPacketRejected`。
    """

    if len(packet) < RTP_HEADER_SIZE:
        return RtpPacketRejected(
            reason="RTP packet is shorter than the fixed 12-byte header"
        )

    if packet[0] != RTP_VERSION_2_HEADER:
        return RtpPacketRejected(
            reason="RTP packet must be V2 with no padding, extension, or CSRC entries"
        )

    if packet[1] != L16_PAYLOAD_TYPE:
        return RtpPacketRejected(reason="RTP packet payload type must be 96 for L16")

    ssrc = RtpSsrc(int.from_bytes(packet[8:12], byteorder="big"))

    if ssrc == 0:
        return RtpPacketRejected(reason="RTP packet SSRC must be nonzero")

    payload = packet[RTP_HEADER_SIZE:]

    if len(payload) != L16_FRAME_BYTES:
        return RtpPacketRejected(
            reason="RTP L16 payload must contain exactly one 20ms frame"
        )

    return RtpPacket(
        sequence=RtpSequence(int.from_bytes(packet[2:4], byteorder="big")),
        timestamp=RtpTimestamp(int.from_bytes(packet[4:8], byteorder="big")),
        ssrc=ssrc,
        payload=payload,
    )
