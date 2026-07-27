from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mic.audio import AudioFrame, SineWaveSpec, generate_sine_wav, replay_wav
from mic.config import load_config
from mic.orchestrator_ws import OrchestratorWebSocketBoundary


@dataclass(slots=True)
class FakeRtpOrchestrator:
    rtp_packets: list[bytes] = field(default_factory=list)
    audio_frames: list[AudioFrame] = field(default_factory=list)

    def receive_rtp_packet(self, packet: bytes) -> None:
        self.rtp_packets.append(packet)

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        self.audio_frames.append(frame)


def rtp_packet(version: int, payload_type: int, payload: bytes) -> bytes:
    return bytes([version << 6, payload_type, 0, 1, 0, 0, 125, 0, 16, 32, 48, 64]) + payload


def test_replay_wav_packetizes_pcm16_frames_as_l16_rtp_from_orchestrator_stream_command(tmp_path: Path) -> None:
    # Given: two deterministic 20ms PCM16 replay frames and canonical stream control.
    fixture = tmp_path / "sine-16k-mono-40ms.wav"
    generate_sine_wav(fixture, SineWaveSpec(duration_ms=40))
    orchestrator = FakeRtpOrchestrator()
    boundary = OrchestratorWebSocketBoundary(load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}))
    boundary.start_rtp_stream(stream_id="mic-primary", start_rtp_timestamp=32000)

    # When: the mic service replays the fixture through its Orchestrator media boundary.
    frames = replay_wav(fixture, boundary, orchestrator)

    # Then: each 20ms frame is delivered as one L16 RTP/AVP packet with a fixed header.
    assert len(orchestrator.rtp_packets) == 2
    assert all(len(packet) == 12 + 640 for packet in orchestrator.rtp_packets)
    assert all(packet[0] == 0x80 for packet in orchestrator.rtp_packets)
    assert all(packet[1] == 96 for packet in orchestrator.rtp_packets)
    sequences = [int.from_bytes(packet[2:4], byteorder="big") for packet in orchestrator.rtp_packets]
    assert sequences[1] == (sequences[0] + 1) % (1 << 16)
    timestamps = [int.from_bytes(packet[4:8], byteorder="big") for packet in orchestrator.rtp_packets]
    assert timestamps == [32000, 32320]
    ssrcs = [int.from_bytes(packet[8:12], byteorder="big") for packet in orchestrator.rtp_packets]
    assert len(set(ssrcs)) == 1
    assert ssrcs[0] != 0
    assert [packet[12:] for packet in orchestrator.rtp_packets] == [
        b"".join(frame.payload[index : index + 2][::-1] for index in range(0, len(frame.payload), 2))
        for frame in frames
    ]


@pytest.mark.parametrize(
    "packet",
    [
        rtp_packet(version=1, payload_type=96, payload=b"\x00" * 640),
        rtp_packet(version=2, payload_type=97, payload=b"\x00" * 640),
        rtp_packet(version=2, payload_type=96, payload=b"\x00" * 639),
    ],
    ids=["wrong_version", "wrong_payload_type", "unaligned_l16_payload"],
)
def test_rtp_boundary_rejects_invalid_l16_packets_without_delivery(packet: bytes) -> None:
    # Given: an RTP packet that violates the L16 RTP media contract.
    orchestrator = FakeRtpOrchestrator()
    boundary = OrchestratorWebSocketBoundary(load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}))

    # When: the media boundary attempts to deliver the malformed RTP packet.
    delivered = boundary.deliver_rtp_packet(orchestrator, packet)

    # Then: it rejects the packet before it reaches Orchestrator.
    assert delivered is False
    assert orchestrator.rtp_packets == []


def test_rtp_packetization_preserves_replay_frame_order_and_20ms_boundaries(tmp_path: Path) -> None:
    # Given: three deterministic 20ms PCM16 replay frames and canonical stream control.
    fixture = tmp_path / "sine-16k-mono-60ms.wav"
    generate_sine_wav(fixture, SineWaveSpec(duration_ms=60))
    orchestrator = FakeRtpOrchestrator()
    boundary = OrchestratorWebSocketBoundary(load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}))
    boundary.start_rtp_stream(stream_id="mic-primary", start_rtp_timestamp=64000)

    # When: replay frames cross the RTP media boundary.
    frames = replay_wav(fixture, boundary, orchestrator)

    # Then: replay retains its existing ordering and one 20ms frame per RTP payload.
    assert [frame.metadata.seq for frame in frames] == [1, 2, 3]
    assert [frame.metadata.duration_ms for frame in frames] == [20, 20, 20]
    assert [len(frame.payload) for frame in frames] == [640, 640, 640]
    assert [packet[12:] for packet in orchestrator.rtp_packets] == [
        b"".join(frame.payload[index : index + 2][::-1] for index in range(0, len(frame.payload), 2))
        for frame in frames
    ]
