"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

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
    """类契约说明.

    职责: 保存 FakeOrchestrator
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: frames。 方法: receive_audio_fr
    ame、receive_rtp_packet。
    """

    frames: list[AudioFrame] = field(default_factory=list)

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        """函数契约说明.

        功能: 执行 receive_audio_frame
        的同步逻辑,并协调 append。
        参数: self 表示当前实例。 frame:
        AudioFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.frames.append(frame)

    def receive_rtp_packet(self, packet: bytes) -> None:
        """函数契约说明.

        功能: 执行 receive_rtp_packet
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `None`。
        """



def test_replay_wav_emits_normalized_pcm16_mono_frames_when_fixture_matches_contract(
    tmp_path: Path,
) -> None:
    # Given: a deterministic one-second 16kHz mono PCM16 WAV fixture.

    """函数契约说明.

    功能: 验证 replay wav emits normalized
    pcm16 mono frames when fixture
    matches contract 的回归场景和可观察结果。
    参数: tmp_path: Path。 必填。
    契约: 同步调用。 返回 `None`。
    """

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

    """函数契约说明.

    功能: 验证 replay wav rejects
    nonconforming stereo fixture with
    observed metadata 的回归场景和可观察结果。
    参数: tmp_path: Path。 必填。
    契约: 同步调用。 返回 `None`。
    """

    fixture = tmp_path / "sine-44k-stereo.wav"

    generate_sine_wav(fixture, SineWaveSpec(sample_rate=44100, channels=2))

    orchestrator = FakeOrchestrator()

    # When/Then: replay rejects it with explicit observed metadata and sends no frame.

    with pytest.raises(
        AudioContractError, match="sample_rate=44100 channels=2 codec=pcm_s16le"
    ):
        replay_wav(fixture, orchestrator)

    assert orchestrator.frames == []
