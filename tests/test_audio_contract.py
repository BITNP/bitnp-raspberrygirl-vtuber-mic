
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mic.audio import (
    AudioContractError,
    AudioFrame,
    SineWaveSpec,
    generate_sine_wav,
    replay_wav,
)


@dataclass(slots=True)
class FakeOrchestrator:

    frames: list[AudioFrame] = field(default_factory=list)

    def receive_audio_frame(self, frame: AudioFrame) -> None:

        self.frames.append(frame)

    def receive_rtp_packet(self, packet: bytes) -> None:
        _ = packet



def test_replay_wav_emits_normalized_pcm16_mono_frames_when_fixture_matches_contract(
    tmp_path: Path,
) -> None:
    # Given: a deterministic one-second 16kHz mono PCM16 WAV fixture.


    fixture = tmp_path / "sine-16k-mono.wav"

    generate_sine_wav(fixture)

    orchestrator = FakeOrchestrator()

    # When: the audio adapter replays the fixture to a frame sink.

    frames = replay_wav(fixture, orchestrator)

    # Then: every frame carries normalized metadata and binary payloads to the sink.

    assert frames == orchestrator.frames

    assert len(frames) == 50

    assert [frame.metadata.seq for frame in frames] == list(range(1, 51))

    assert {frame.metadata.sample_rate for frame in frames} == {16000}

    assert {frame.metadata.channels for frame in frames} == {1}

    assert {frame.metadata.codec for frame in frames} == {"pcm_s16le"}

    assert {frame.metadata.duration_ms for frame in frames} == {20}

    assert all(frame.metadata.byte_length == len(frame.payload) for frame in frames)

    assert all(
        isinstance(frame.payload, bytes) and len(frame.payload) == 640
        for frame in frames
    )


def test_replay_wav_rejects_nonconforming_stereo_fixture_with_observed_metadata(
    tmp_path: Path,
) -> None:
    # Given: a deterministic WAV fixture outside the mic contract.


    fixture = tmp_path / "sine-44k-stereo.wav"

    generate_sine_wav(fixture, SineWaveSpec(sample_rate=44100, channels=2))

    orchestrator = FakeOrchestrator()

    # When/Then: replay rejects it with explicit observed metadata and sends no frame.

    with pytest.raises(
        AudioContractError, match="sample_rate=44100 channels=2 codec=pcm_s16le"
    ):
        replay_wav(fixture, orchestrator)

    assert orchestrator.frames == []
