"""模块契约说明.

职责: 提供 mic.audio 模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import math
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NewType, Protocol

SampleRate = NewType("SampleRate", int)

ChannelCount = NewType("ChannelCount", int)

DurationMs = NewType("DurationMs", int)

ByteLength = NewType("ByteLength", int)

FrameSeq = NewType("FrameSeq", int)


PCM16_MONO_SAMPLE_RATE: Final = SampleRate(16000)

PCM16_MONO_CHANNELS: Final = ChannelCount(1)

PCM16_BYTES_PER_SAMPLE: Final = 2

PCM16_CODEC: Final = "pcm_s16le"

DEFAULT_CHUNK_DURATION_MS: Final = DurationMs(20)

DEFAULT_SINE_FREQUENCY_HZ: Final = 440.0

DEFAULT_SINE_AMPLITUDE: Final = 12000


@dataclass(frozen=True, slots=True)
class AudioContractError(Exception):
    """类契约说明.

    职责: 保存 AudioContractError
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: sample_rate、channels、codec。
    方法: __str__。
    """

    sample_rate: int

    channels: int

    codec: str

    def __str__(self) -> str:
        """函数契约说明.

        功能: 生成面向日志、错误或调试输出的稳定文本表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return f"unsupported audio contract sample_rate={self.sample_rate} channels={self.channels} codec={self.codec}"


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    """类契约说明.

    职责: 保存 AudioMetadata
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: seq、sample_rate、channels、cod
    ec、duration_ms、byte_length。
    """

    seq: FrameSeq

    sample_rate: SampleRate

    channels: ChannelCount

    codec: str

    duration_ms: DurationMs

    byte_length: ByteLength


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """类契约说明.

    职责: 保存 AudioFrame
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: metadata、payload。
    """

    metadata: AudioMetadata

    payload: bytes


class AudioFrameSink(Protocol):
    """类契约说明.

    职责: 声明 AudioFrameSink
    协议接口,约束实现方必须提供的行为。
    契约: 方法: receive_audio_frame。
    """

    def receive_audio_frame(self, frame: AudioFrame) -> None:
        """函数契约说明.

        功能: 执行 receive_audio_frame
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 frame:
        AudioFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...


@dataclass(frozen=True, slots=True)
class SineWaveSpec:
    """类契约说明.

    职责: 保存 SineWaveSpec
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: sample_rate、channels、duratio
    n_ms、frequency_hz。
    """

    sample_rate: int = PCM16_MONO_SAMPLE_RATE

    channels: int = PCM16_MONO_CHANNELS

    duration_ms: int = 1000

    frequency_hz: float = DEFAULT_SINE_FREQUENCY_HZ


DEFAULT_SINE_WAVE_SPEC: Final = SineWaveSpec()


@dataclass(frozen=True, slots=True)
class WavAudio:
    """类契约说明.

    职责: 保存 WavAudio 不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    sample_rate、channels、codec、pcm。
    """

    sample_rate: SampleRate

    channels: ChannelCount

    codec: str

    pcm: bytes


def generate_sine_wav(path: Path, spec: SineWaveSpec = DEFAULT_SINE_WAVE_SPEC) -> None:
    """函数契约说明.

    功能: 执行 generate_sine_wav 的同步逻辑,并协调
    bytearray, range, int, to_bytes。
    参数: path: Path。 必填。 spec:
    SineWaveSpec。 可省略。
    契约: 同步调用。 返回 `None`。
    """

    sample_count = spec.sample_rate * spec.duration_ms // 1000

    frames = bytearray()

    for sample_index in range(sample_count):
        value = int(
            DEFAULT_SINE_AMPLITUDE
            * math.sin(
                2 * math.pi * spec.frequency_hz * sample_index / spec.sample_rate
            )
        )

        sample = value.to_bytes(PCM16_BYTES_PER_SAMPLE, byteorder="little", signed=True)

        for _ in range(spec.channels):
            frames.extend(sample)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(spec.channels)

        wav_file.setsampwidth(PCM16_BYTES_PER_SAMPLE)

        wav_file.setframerate(spec.sample_rate)

        wav_file.writeframes(bytes(frames))


def replay_wav(path: Path, sink: AudioFrameSink) -> list[AudioFrame]:
    """函数契约说明.

    功能: 执行 replay_wav 的同步逻辑,并协调
    read_wav_audio、list、chunk_audio、
    receive_audio_frame。
    参数: path: Path。 必填。 sink:
    AudioFrameSink。 必填。
    契约: 同步调用。 返回 `list[AudioFrame]`。
    """

    audio = read_wav_audio(path)

    frames = list(chunk_audio(audio, DEFAULT_CHUNK_DURATION_MS))

    for frame in frames:
        sink.receive_audio_frame(frame)

    return frames


def read_wav_audio(path: Path) -> WavAudio:
    """函数契约说明.

    功能: 执行 read_wav_audio 的同步逻辑,并协调
    codec_from_sample_width, WavAudio,
    open, getnchannels。
    参数: path: Path。 必填。
    契约: 同步调用。 返回 `WavAudio`。 可能抛出
    AudioContractError。
    """

    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()

        sample_rate = wav_file.getframerate()

        sample_width = wav_file.getsampwidth()

        pcm = wav_file.readframes(wav_file.getnframes())

    codec = codec_from_sample_width(sample_width)

    if (
        sample_rate != PCM16_MONO_SAMPLE_RATE
        or channels != PCM16_MONO_CHANNELS
        or codec != PCM16_CODEC
    ):
        raise AudioContractError(
            sample_rate=sample_rate, channels=channels, codec=codec
        )

    return WavAudio(
        sample_rate=SampleRate(sample_rate),
        channels=ChannelCount(channels),
        codec=codec,
        pcm=pcm,
    )


def codec_from_sample_width(sample_width: int) -> str:
    """函数契约说明.

    功能: 执行 codec_from_sample_width
    的同步逻辑,并维持签名契约。
    参数: sample_width: int。 必填。
    契约: 同步调用。 返回 `str`。
    """

    if sample_width == PCM16_BYTES_PER_SAMPLE:
        return PCM16_CODEC

    return f"pcm_s{sample_width * 8}le"


def chunk_audio(audio: WavAudio, chunk_duration_ms: DurationMs) -> Iterator[AudioFrame]:
    """函数契约说明.

    功能: 执行 chunk_audio 的同步逻辑,并协调
    enumerate, range, int, len。
    参数: audio: WavAudio。 必填。
    chunk_duration_ms: DurationMs。 必填。
    契约: 同步调用。 返回迭代或生成器协议。 返回
    `Iterator[AudioFrame]`。
    """

    chunk_size = (
        int(audio.sample_rate)
        * int(audio.channels)
        * PCM16_BYTES_PER_SAMPLE
        * int(chunk_duration_ms)
        // 1000
    )

    for index, start in enumerate(range(0, len(audio.pcm), chunk_size), start=1):
        payload = audio.pcm[start : start + chunk_size]

        yield AudioFrame(
            metadata=AudioMetadata(
                seq=FrameSeq(index),
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                codec=audio.codec,
                duration_ms=duration_from_byte_length(ByteLength(len(payload)), audio),
                byte_length=ByteLength(len(payload)),
            ),
            payload=payload,
        )


def duration_from_byte_length(byte_length: ByteLength, audio: WavAudio) -> DurationMs:
    """函数契约说明.

    功能: 执行 duration_from_byte_length
    的同步逻辑,并协调 DurationMs, int。
    参数: byte_length: ByteLength。 必填。
    audio: WavAudio。 必填。
    契约: 同步调用。 返回 `DurationMs`。
    """

    bytes_per_second = (
        int(audio.sample_rate) * int(audio.channels) * PCM16_BYTES_PER_SAMPLE
    )

    return DurationMs(int(byte_length) * 1000 // bytes_per_second)
