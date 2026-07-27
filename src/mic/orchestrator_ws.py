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
    """Owns stream-control state while media crosses the RTP boundary in memory."""

    __slots__ = ("_stream", "config")

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self._stream: RtpStream | None = None

    def target_url(self) -> OrchestratorWsUrl:
        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        return "mic WebSocket boundary placeholder targets Orchestrator only"

    def start_rtp_stream(self, stream_id: str, start_rtp_timestamp: int) -> None:
        self._stream = RtpStream(
            stream_id=stream_id,
            sequence=RtpSequence(0),
            timestamp=RtpTimestamp(start_rtp_timestamp),
            ssrc=MIC_RTP_SSRC,
        )

    def send_audio_frame(self, sink: AudioRtpSink, frame: AudioFrame) -> None:
        stream = self._stream
        if stream is None:
            sink.receive_audio_frame(frame)
            return
        packet, self._stream = packetize_l16_pcm16le(frame.payload, stream)
        self.deliver_rtp_packet(sink, packet)

    def deliver_rtp_packet(self, sink: AudioRtpSink, packet: bytes) -> bool:
        parsed = parse_l16_rtp_packet(packet)
        match parsed:
            case RtpPacketRejected():
                return False
            case RtpPacket():
                sink.receive_rtp_packet(packet)
                return True
            case unreachable:
                assert_never(unreachable)
