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
    sample_rate: int
    channels: int
    codec: str

    def __str__(self) -> str:
        return f"unsupported audio contract sample_rate={self.sample_rate} channels={self.channels} codec={self.codec}"


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    seq: FrameSeq
    sample_rate: SampleRate
    channels: ChannelCount
    codec: str
    duration_ms: DurationMs
    byte_length: ByteLength


@dataclass(frozen=True, slots=True)
class AudioFrame:
    metadata: AudioMetadata
    payload: bytes


class AudioFrameSink(Protocol):
    def receive_audio_frame(self, frame: AudioFrame) -> None: ...


class AudioFrameBoundary(Protocol):
    def send_audio_frame(self, sink: AudioFrameSink, frame: AudioFrame) -> None: ...


@dataclass(frozen=True, slots=True)
class SineWaveSpec:
    sample_rate: int = PCM16_MONO_SAMPLE_RATE
    channels: int = PCM16_MONO_CHANNELS
    duration_ms: int = 1000
    frequency_hz: float = DEFAULT_SINE_FREQUENCY_HZ


DEFAULT_SINE_WAVE_SPEC: Final = SineWaveSpec()


@dataclass(frozen=True, slots=True)
class WavAudio:
    sample_rate: SampleRate
    channels: ChannelCount
    codec: str
    pcm: bytes


def generate_sine_wav(path: Path, spec: SineWaveSpec = DEFAULT_SINE_WAVE_SPEC) -> None:
    sample_count = spec.sample_rate * spec.duration_ms // 1000
    frames = bytearray()
    for sample_index in range(sample_count):
        value = int(DEFAULT_SINE_AMPLITUDE * math.sin(2 * math.pi * spec.frequency_hz * sample_index / spec.sample_rate))
        sample = value.to_bytes(PCM16_BYTES_PER_SAMPLE, byteorder="little", signed=True)
        for _ in range(spec.channels):
            frames.extend(sample)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(spec.channels)
        wav_file.setsampwidth(PCM16_BYTES_PER_SAMPLE)
        wav_file.setframerate(spec.sample_rate)
        wav_file.writeframes(bytes(frames))


def replay_wav(path: Path, boundary: AudioFrameBoundary, sink: AudioFrameSink) -> list[AudioFrame]:
    audio = read_wav_audio(path)
    frames = list(chunk_audio(audio, DEFAULT_CHUNK_DURATION_MS))
    for frame in frames:
        boundary.send_audio_frame(sink, frame)
    return frames


def read_wav_audio(path: Path) -> WavAudio:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        pcm = wav_file.readframes(wav_file.getnframes())
    codec = codec_from_sample_width(sample_width)
    if sample_rate != PCM16_MONO_SAMPLE_RATE or channels != PCM16_MONO_CHANNELS or codec != PCM16_CODEC:
        raise AudioContractError(sample_rate=sample_rate, channels=channels, codec=codec)
    return WavAudio(
        sample_rate=SampleRate(sample_rate),
        channels=ChannelCount(channels),
        codec=codec,
        pcm=pcm,
    )


def codec_from_sample_width(sample_width: int) -> str:
    if sample_width == PCM16_BYTES_PER_SAMPLE:
        return PCM16_CODEC
    return f"pcm_s{sample_width * 8}le"


def chunk_audio(audio: WavAudio, chunk_duration_ms: DurationMs) -> Iterator[AudioFrame]:
    chunk_size = int(audio.sample_rate) * int(audio.channels) * PCM16_BYTES_PER_SAMPLE * int(chunk_duration_ms) // 1000
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
    bytes_per_second = int(audio.sample_rate) * int(audio.channels) * PCM16_BYTES_PER_SAMPLE
    return DurationMs(int(byte_length) * 1000 // bytes_per_second)
