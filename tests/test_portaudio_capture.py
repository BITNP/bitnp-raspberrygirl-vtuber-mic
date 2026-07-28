from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import pytest

from mic.audio import AudioFrame
from mic.config import load_config
from mic.orchestrator_ws import OrchestratorWebSocketBoundary
from mic.portaudio_capture import CaptureDevice, PortAudioCaptureSource, RawInputStream


@dataclass(slots=True)
class FakeRawInputStream:
    data: bytes
    overflowed: bool = False
    read_error: RuntimeError | None = None
    read_sizes: list[int] = field(default_factory=list)
    entered: bool = False
    exited: bool = False

    def __enter__(self) -> Self:
        self.entered = True
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True

    def read(self, frames: int) -> tuple[bytes, bool]:
        self.read_sizes.append(frames)
        if self.read_error is not None:
            raise self.read_error
        return self.data, self.overflowed


@dataclass(slots=True)
class FakeRawInputStreamFactory:
    stream: RawInputStream
    devices: list[CaptureDevice] = field(default_factory=list)

    def __call__(self, device: CaptureDevice) -> RawInputStream:
        self.devices.append(device)
        return self.stream


@dataclass(slots=True)
class FakeRtpOrchestrator:
    rtp_packets: list[bytes] = field(default_factory=list)
    audio_frames: list[AudioFrame] = field(default_factory=list)

    def receive_rtp_packet(self, packet: bytes) -> None:
        self.rtp_packets.append(packet)

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        self.audio_frames.append(frame)


def _active_boundary() -> OrchestratorWebSocketBoundary:
    boundary = OrchestratorWebSocketBoundary(load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}))
    boundary.start_rtp_stream(stream_id="mic-primary", start_rtp_timestamp=32000)
    return boundary


def test_capture_forwards_one_exact_pcm16le_frame_as_rtp_when_stream_returns_one_block() -> None:
    # Given: a stream yields exactly one 20 ms PCM16 mono block and RTP stream control exists.
    payload = bytes(range(256)) * 2 + bytes(range(128))
    stream = FakeRawInputStream(data=payload)
    factory = FakeRawInputStreamFactory(stream=stream)
    source = PortAudioCaptureSource(device="Microphone", stream_factory=factory)
    orchestrator = FakeRtpOrchestrator()

    # When: the source captures and forwards one fixed-size block.
    frame = source.capture_and_send(_active_boundary(), orchestrator)

    # Then: it requests 320 samples, sends one L16 RTP packet, and closes the stream.
    assert frame is not None
    assert frame.payload == payload
    assert frame.metadata.byte_length == 640
    assert factory.devices == ["Microphone"]
    assert stream.read_sizes == [320]
    assert [packet[12:] for packet in orchestrator.rtp_packets] == [
        b"".join(payload[index : index + 2][::-1] for index in range(0, len(payload), 2))
    ]
    assert stream.entered is True
    assert stream.exited is True


def test_capture_rejects_short_stream_read_without_rtp_delivery() -> None:
    # Given: a stream returns fewer bytes than one 20 ms PCM16 mono block.
    stream = FakeRawInputStream(data=b"\x00" * 639)
    source = PortAudioCaptureSource(device=None, stream_factory=FakeRawInputStreamFactory(stream=stream))
    orchestrator = FakeRtpOrchestrator()

    # When: capture receives the truncated read.
    frame = source.capture_and_send(_active_boundary(), orchestrator)

    # Then: it returns no frame, emits no RTP, and releases the stream.
    assert frame is None
    assert orchestrator.rtp_packets == []
    assert stream.exited is True


def test_capture_normalizes_big_endian_int16_bytes_before_packetization() -> None:
    # Given: a big-endian host stream yields one frame of native-endian int16 samples.
    native_payload = b"\x12\x34" * 320
    stream = FakeRawInputStream(data=native_payload)
    source = PortAudioCaptureSource(
        device=None,
        stream_factory=FakeRawInputStreamFactory(stream=stream),
        byteorder="big",
    )
    orchestrator = FakeRtpOrchestrator()

    # When: the source captures one frame.
    frame = source.capture_and_send(_active_boundary(), orchestrator)

    # Then: frame payload is canonical PCM16LE and RTP payload remains L16 network order.
    assert frame is not None
    assert frame.payload == b"\x34\x12" * 320
    assert orchestrator.rtp_packets[0][12:] == native_payload


def test_capture_closes_stream_when_read_raises() -> None:
    # Given: the stream fails while the fixed block is being read.
    stream = FakeRawInputStream(data=b"", read_error=RuntimeError("read failed"))
    source = PortAudioCaptureSource(device=None, stream_factory=FakeRawInputStreamFactory(stream=stream))

    # When / Then: the read error propagates after context-managed stream cleanup.
    with pytest.raises(RuntimeError, match="read failed"):
        source.capture_and_send(_active_boundary(), FakeRtpOrchestrator())
    assert stream.entered is True
    assert stream.exited is True
