from mic.rtp import (
    L16_FRAME_BYTES,
    MIC_RTP_SSRC,
    RtpPacket,
    RtpPacketRejected,
    RtpSequence,
    RtpStream,
    RtpTimestamp,
    packetize_l16_pcm16le,
    parse_l16_rtp_packet,
)


def test_packetize_l16_pcm16le_preserves_fixed_frame_order_and_advances_clock() -> None:
    # Given: one canonical 20 ms PCM16LE frame and a configured Mic RTP stream.
    payload = b"\x10\x20" * 320
    stream = RtpStream(
        stream_id="mic-primary",
        sequence=RtpSequence(7),
        timestamp=RtpTimestamp(32_000),
        ssrc=MIC_RTP_SSRC,
    )

    # When: the pure RTP adapter packetizes the frame.
    packet, next_stream = packetize_l16_pcm16le(payload, stream)

    # Then: the packet is fixed V2/PT96/L16 and the stream advances by one 20 ms frame.
    assert packet[:12] == b"\x80\x60\x00\x07\x00\x00}\x00MIC1"
    assert packet[12:] == b"\x20\x10" * 320
    assert next_stream.sequence == RtpSequence(8)
    assert next_stream.timestamp == RtpTimestamp(32_320)


def test_parse_l16_rtp_packet_rejects_invalid_fixed_frame() -> None:
    # Given: a V2/PT96 packet whose payload is one byte short of the fixed L16 frame.
    packet = b"\x80\x60\x00\x01\x00\x00}\x00MIC1" + b"\x00" * (
        L16_FRAME_BYTES - 1
    )

    # When: the pure RTP boundary parses the packet.
    parsed = parse_l16_rtp_packet(packet)

    # Then: malformed media cannot pass into the transport path.
    assert parsed == RtpPacketRejected(
        reason="RTP L16 payload must contain exactly one 20ms frame"
    )


def test_parse_l16_rtp_packet_accepts_canonical_packet() -> None:
    # Given: a canonical RTP packet emitted from the pure packetizer.
    packet, _next_stream = packetize_l16_pcm16le(
        b"\x01\x02" * 320,
        RtpStream(
            stream_id="mic-primary",
            sequence=RtpSequence(0),
            timestamp=RtpTimestamp(0),
            ssrc=MIC_RTP_SSRC,
        ),
    )

    # When: the boundary parses the packet.
    parsed = parse_l16_rtp_packet(packet)

    # Then: it returns the typed RTP packet with the one-frame L16 payload.
    assert parsed == RtpPacket(
        sequence=RtpSequence(0),
        timestamp=RtpTimestamp(0),
        ssrc=MIC_RTP_SSRC,
        payload=b"\x02\x01" * 320,
    )
