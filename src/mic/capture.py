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
    def write(self, packet: bytes) -> int: ...

    def flush(self) -> None: ...


class ConsoleRtpPacketOutput:
    __slots__ = ()

    def write(self, packet: bytes) -> int:
        return sys.stdout.buffer.write(packet)

    def flush(self) -> None:
        sys.stdout.buffer.flush()


@dataclass(frozen=True, slots=True)
class CaptureRuntimeConfig:
    service_config: ServiceConfig
    device: CaptureDevice
    stream_id: str
    start_timestamp: RtpStartTimestamp


class StdoutRtpSink:
    __slots__ = ("_output",)

    def __init__(self, output: RtpPacketOutput) -> None:
        self._output = output

    def receive_rtp_packet(self, packet: bytes) -> None:
        self._output.write(packet)
        self._output.flush()

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        raise ConfigError(key=RTP_STREAM_ID_KEY, reason=f"stream must be active before writing frame {frame.metadata.seq}")


def load_capture_runtime_config(env: Mapping[str, str] | None = None) -> CaptureRuntimeConfig:
    source = os.environ if env is None else env
    raw_stream_id = _required_value(source, RTP_STREAM_ID_KEY)
    raw_timestamp = _required_value(source, RTP_TIMESTAMP_KEY)
    try:
        timestamp = int(raw_timestamp)
    except ValueError as exc:
        raise ConfigError(key=RTP_TIMESTAMP_KEY, reason="must be an integer") from exc
    if not 0 <= timestamp < 1 << 32:
        raise ConfigError(key=RTP_TIMESTAMP_KEY, reason="must be an unsigned 32-bit integer")
    return CaptureRuntimeConfig(
        service_config=load_config(source),
        device=_capture_device(source),
        stream_id=raw_stream_id,
        start_timestamp=RtpStartTimestamp(timestamp),
    )


def run_capture(env: Mapping[str, str], stream_factory: RawInputStreamFactory, output: RtpPacketOutput) -> int:
    config = load_capture_runtime_config(env)
    boundary = OrchestratorWebSocketBoundary(config.service_config)
    boundary.start_rtp_stream(config.stream_id, config.start_timestamp)
    frame = PortAudioCaptureSource(device=config.device, stream_factory=stream_factory).capture_and_send(
        boundary, StdoutRtpSink(output)
    )
    return 0 if frame is not None else 1


def main() -> int:
    return run_capture(os.environ, open_raw_input_stream, ConsoleRtpPacketOutput())


def _required_value(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if value == "":
        raise ConfigError(key=key, reason="must be configured")
    return value


def _capture_device(env: Mapping[str, str]) -> CaptureDevice:
    value = env.get(CAPTURE_DEVICE_KEY, "").strip()
    if value == "" or value == "default":
        return None
    if value.isdecimal():
        return int(value)
    return value
