
from __future__ import annotations

import os
from pathlib import Path

import pytest

from mic.audio import generate_sine_wav, read_wav_audio
from mic.portaudio_capture import CaptureDevice, PortAudioCaptureSource

MIC_WAV_ENV = "BITNP_REAL_MIC_WAV_PATH"

FAKE_LOCAL_ENV = "BITNP_REAL_ADAPTER_FAKE_LOCAL"

MALFORMED_ENV = "BITNP_REAL_ADAPTER_MALFORMED_CHECK"

CAPTURE_DEVICE_ENV = "BITNP_CAPTURE_DEVICE"


@pytest.mark.real_adapter
def test_live_microphone_capture_smoke_when_explicitly_enabled(tmp_path: Path) -> None:
    # Given: either a fake local capture file or an explicit live microphone capture artifact.


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


    if os.environ.get(MALFORMED_ENV) != "1":
        pytest.skip(f"set {MALFORMED_ENV}=1 to run malformed microphone smoke")

    missing = tmp_path / "missing-live-capture.wav"

    # When / Then: a missing capture artifact reports a clear readiness failure.

    with pytest.raises(FileNotFoundError, match="missing-live-capture"):
        read_wav_audio(missing)


@pytest.mark.real_adapter
def test_portaudio_capture_reads_one_frame_when_explicit_device_is_configured() -> (
    None
):
    # Given: an explicitly selected PortAudio capture device.


    raw_device = os.environ.get(CAPTURE_DEVICE_ENV, "").strip()

    if raw_device == "":
        pytest.skip(f"set {CAPTURE_DEVICE_ENV} to run PortAudio capture smoke")

    device: CaptureDevice = int(raw_device) if raw_device.isdecimal() else raw_device

    # When: the real PortAudio adapter captures one fixed audio frame.

    frame = PortAudioCaptureSource(device=device).capture_one()

    # Then: capture produces one complete PCM16 frame.

    assert frame is not None

    assert len(frame.payload) == 640


def _mic_wav_path_or_skip(tmp_path: Path) -> Path:

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
