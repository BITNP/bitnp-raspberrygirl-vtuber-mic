from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from mic.capture import load_capture_runtime_config, run_capture
from mic.portaudio_capture import CaptureDevice, RawInputStream


@dataclass(slots=True)
class FakeRawInputStream:
    data: bytes
    read_sizes: list[int] = field(default_factory=list)
    exited: bool = False

    def __enter__(self) -> Self:
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
        return self.data, False


@dataclass(slots=True)
class FakeRawInputStreamFactory:
    stream: RawInputStream
    devices: list[CaptureDevice] = field(default_factory=list)

    def __call__(self, device: CaptureDevice) -> RawInputStream:
        self.devices.append(device)
        return self.stream


@dataclass(slots=True)
class FakeStdout:
    writes: list[bytes] = field(default_factory=list)

    def write(self, packet: bytes) -> int:
        self.writes.append(packet)
        return len(packet)

    def flush(self) -> None:
        return None


def test_run_capture_packetizes_one_configured_portaudio_frame_to_stdout_without_hardware() -> None:
    # Given: explicit capture and stream settings plus an injected RawInputStream.
    payload = bytes(range(256)) * 2 + bytes(range(128))
    stream = FakeRawInputStream(data=payload)
    factory = FakeRawInputStreamFactory(stream=stream)
    output = FakeStdout()
    env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_CAPTURE_DEVICE": "12",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: the production capture composition runs through the existing boundary.
    exit_code = run_capture(env, factory, output)

    # Then: it writes exactly one packetized L16 frame to stdout and closes the stream.
    assert exit_code == 0
    assert len(output.writes) == 1
    assert len(output.writes[0]) == 12 + 640
    assert output.writes[0][4:8] == (96000).to_bytes(4, byteorder="big")
    assert output.writes[0][12:] == b"".join(payload[index : index + 2][::-1] for index in range(0, len(payload), 2))
    assert factory.devices == [12]
    assert stream.read_sizes == [320]
    assert stream.exited is True


def test_load_capture_runtime_config_uses_default_or_name_capture_device() -> None:
    # Given: required RTP settings and either omitted or named neutral capture device selection.
    required_env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: runtime configuration is parsed from each selection form.
    default_config = load_capture_runtime_config(required_env)
    named_config = load_capture_runtime_config({**required_env, "BITNP_CAPTURE_DEVICE": "USB Microphone"})

    # Then: omission uses the host default while a query remains a name.
    assert default_config.device is None
    assert named_config.device == "USB Microphone"


def test_load_capture_runtime_config_uses_portaudio_default_for_default_device_literal() -> None:
    # Given: required RTP settings and the documented default device literal.
    env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_CAPTURE_DEVICE": "default",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: runtime configuration parses the literal.
    config = load_capture_runtime_config(env)

    # Then: it uses PortAudio's None default-device selector.
    assert config.device is None
