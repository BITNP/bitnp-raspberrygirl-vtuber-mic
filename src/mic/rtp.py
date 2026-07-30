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
    stream_id: str
    sequence: RtpSequence
    timestamp: RtpTimestamp
    ssrc: RtpSsrc


@dataclass(frozen=True, slots=True)
class RtpPacket:
    sequence: RtpSequence
    timestamp: RtpTimestamp
    ssrc: RtpSsrc
    payload: bytes


@dataclass(frozen=True, slots=True)
class RtpPacketRejected:
    reason: str


def packetize_l16_pcm16le(payload: bytes, stream: RtpStream) -> tuple[bytes, RtpStream]:
    """Encode one PCM16 little-endian replay frame as a fixed-header L16 RTP packet."""
    l16_payload = b"".join(payload[index : index + 2][::-1] for index in range(0, len(payload), 2))
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
        timestamp=RtpTimestamp((int(stream.timestamp) + RTP_SAMPLES_PER_20MS_FRAME) % (1 << 32)),
        ssrc=stream.ssrc,
    )
    return packet, next_stream


def parse_l16_rtp_packet(packet: bytes) -> RtpPacket | RtpPacketRejected:
    """Parse only the fixed V2/PT96 L16 RTP profile accepted by Mic."""
    if len(packet) < RTP_HEADER_SIZE:
        return RtpPacketRejected(reason="RTP packet is shorter than the fixed 12-byte header")
    if packet[0] != RTP_VERSION_2_HEADER:
        return RtpPacketRejected(reason="RTP packet must be V2 with no padding, extension, or CSRC entries")
    if packet[1] != L16_PAYLOAD_TYPE:
        return RtpPacketRejected(reason="RTP packet payload type must be 96 for L16")
    ssrc = RtpSsrc(int.from_bytes(packet[8:12], byteorder="big"))
    if ssrc == 0:
        return RtpPacketRejected(reason="RTP packet SSRC must be nonzero")
    payload = packet[RTP_HEADER_SIZE:]
    if len(payload) != L16_FRAME_BYTES:
        return RtpPacketRejected(reason="RTP L16 payload must contain exactly one 20ms frame")
    return RtpPacket(
        sequence=RtpSequence(int.from_bytes(packet[2:4], byteorder="big")),
        timestamp=RtpTimestamp(int.from_bytes(packet[4:8], byteorder="big")),
        ssrc=ssrc,
        payload=payload,
    )
