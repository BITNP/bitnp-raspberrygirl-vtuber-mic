"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mic.audio import AudioFrame, generate_sine_wav, read_wav_audio
from mic.config import load_config
from mic.orchestrator_ws import OrchestratorWebSocketBoundary
from mic.portaudio_capture import CaptureDevice, PortAudioCaptureSource

MIC_WAV_ENV = "BITNP_REAL_MIC_WAV_PATH"

FAKE_LOCAL_ENV = "BITNP_REAL_ADAPTER_FAKE_LOCAL"

MALFORMED_ENV = "BITNP_REAL_ADAPTER_MALFORMED_CHECK"

CAPTURE_DEVICE_ENV = "BITNP_CAPTURE_DEVICE"


class LiveCaptureOrchestrator:
    """类契约说明.

    职责: 定义 LiveCaptureOrchestrator
    的状态、行为和对外协作边界。
    契约: 方法: __init__、receive_rtp_packet、
    receive_audio_frame。
    """

    def __init__(self) -> None:
        """函数契约说明.

        功能: 初始化 LiveCaptureOrchestrator
        的字段并建立实例不变式。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.rtp_packets: list[bytes] = []

    def receive_rtp_packet(self, packet: bytes) -> None:
        """函数契约说明.

        功能: 执行 receive_rtp_packet
        的同步逻辑,并协调 append。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        self.rtp_packets.append(packet)

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        """函数契约说明.

        功能: 执行 receive_audio_frame
        的同步逻辑,并协调 AssertionError。
        参数: self 表示当前实例。 frame:
        AudioFrame。 必填。
        契约: 同步调用。 返回 `None`。 可能抛出
        AssertionError。
        """

        raise AssertionError(
            f"expected RTP delivery, received raw frame {frame.metadata.seq}"
        )


@pytest.mark.real_adapter
def test_live_microphone_capture_smoke_when_explicitly_enabled(tmp_path: Path) -> None:
    # Given: either a fake local capture file or an explicit live microphone capture artifact.

    """函数契约说明.

    功能: 验证 live microphone capture smoke
    when explicitly enabled 的回归场景和可观察结果。
    参数: tmp_path: Path。 必填。
    契约: 同步调用。 返回 `None`。
    """

    wav_path = _mic_wav_path_or_skip(tmp_path)

    # When: the mic boundary reads the capture as normalized PCM16 mono audio.

    audio = read_wav_audio(wav_path)

    # Then: the live/fake capture satisfies the Orchestrator audio contract.

    assert audio.sample_rate == 16000

    assert audio.channels == 1

    assert audio.codec == "pcm_s16le"

    assert len(audio.pcm) > 0


@pytest.mark.real_adapter
def test_live_microphone_malformed_capture_reports_contract_error(
    tmp_path: Path,
) -> None:
    # Given: malformed endpoint checking is explicitly enabled.

    """函数契约说明.

    功能: 验证 live microphone malformed
    capture reports contract error
    的回归场景和可观察结果。
    参数: tmp_path: Path。 必填。
    契约: 同步调用。 返回 `None`。
    """

    if os.environ.get(MALFORMED_ENV) != "1":
        pytest.skip(f"set {MALFORMED_ENV}=1 to run malformed microphone smoke")

    missing = tmp_path / "missing-live-capture.wav"

    # When / Then: a missing capture artifact reports a clear readiness failure.

    with pytest.raises(FileNotFoundError, match="missing-live-capture"):
        read_wav_audio(missing)


@pytest.mark.real_adapter
def test_portaudio_capture_emits_one_rtp_packet_when_explicit_device_is_configured() -> (
    None
):
    # Given: an explicitly selected PortAudio capture device.

    """函数契约说明.

    功能: 验证 portaudio capture emits one
    rtp packet when explicit device is
    configured 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    raw_device = os.environ.get(CAPTURE_DEVICE_ENV, "").strip()

    if raw_device == "":
        pytest.skip(f"set {CAPTURE_DEVICE_ENV} to run PortAudio capture smoke")

    device: CaptureDevice = int(raw_device) if raw_device.isdecimal() else raw_device

    boundary = OrchestratorWebSocketBoundary(
        load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"})
    )

    boundary.start_rtp_stream(stream_id="portaudio-smoke", start_rtp_timestamp=0)

    orchestrator = LiveCaptureOrchestrator()

    # When: the real PortAudio adapter captures one fixed audio frame.

    frame = PortAudioCaptureSource(device=device).capture_and_send(
        boundary, orchestrator
    )

    # Then: capture produces one complete frame and one in-memory RTP packet.

    assert frame is not None

    assert len(frame.payload) == 640

    assert len(orchestrator.rtp_packets) == 1


def _mic_wav_path_or_skip(tmp_path: Path) -> Path:
    """函数契约说明.

    功能: 执行 _mic_wav_path_or_skip
    的同步逻辑,并协调 strip, Path, get,
    generate_sine_wav。
    参数: tmp_path: Path。 必填。
    契约: 同步调用。 返回 `Path`。
    """

    if os.environ.get(FAKE_LOCAL_ENV) == "1":
        wav_path = tmp_path / "fake-local-mic.wav"

        generate_sine_wav(wav_path)

        return wav_path

    configured = os.environ.get(MIC_WAV_ENV, "").strip()

    if configured == "":
        pytest.skip(
            f"set {MIC_WAV_ENV} or {FAKE_LOCAL_ENV}=1 to run live microphone smoke"
        )

    return Path(configured)
