"""模块契约说明.

职责: 提供 mic.portaudio_capture
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import asyncio  # noqa: ANYIO_OK - PortAudio reads run off the asyncio UDP event loop.
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Literal, Protocol, Self

import sounddevice

from mic.audio import (
    DEFAULT_CHUNK_DURATION_MS,
    PCM16_CODEC,
    PCM16_MONO_CHANNELS,
    PCM16_MONO_SAMPLE_RATE,
    AudioFrame,
    AudioFrameBoundary,
    AudioMetadata,
    AudioRtpSink,
    ByteLength,
    FrameSeq,
)

type CaptureDevice = int | str | None

type HostByteOrder = Literal["little", "big"]

PCM16_MONO_20MS_FRAME_BYTES: Final = ByteLength(640)

PCM16_MONO_20MS_FRAME_SAMPLES: Final = 320

DEFAULT_HOST_BYTEORDER: Final[HostByteOrder] = (
    "little" if sys.byteorder == "little" else "big"
)


@dataclass(frozen=True, slots=True)
class CaptureStateError(RuntimeError):
    """类契约说明.

    职责: 保存 CaptureStateError
    不可变数据结构,用类型标注表达字段契约。
    契约: 方法: __str__。
    """

    def __str__(self) -> str:
        """函数契约说明.

        功能: 生成面向日志、错误或调试输出的稳定文本表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return "PortAudio capture must open before reading"


class RawInputStream(Protocol):
    """类契约说明.

    职责: 声明 RawInputStream
    协议接口,约束实现方必须提供的行为。
    契约: 方法: __enter__、__exit__、read。
    """

    def __enter__(self) -> Self:
        """函数契约说明.

        功能: 执行 __enter__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `Self`。
        """

        ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """函数契约说明.

        功能: 执行 __exit__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 exception_type:
        type[BaseException] | None。 必填。
        exception: BaseException | None。
        必填。 traceback: TracebackType |
        None。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def read(self, frames: int) -> tuple[bytes, bool]:
        """函数契约说明.

        功能: 执行 read 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 frames: int。
        必填。
        契约: 同步调用。 返回 `tuple[bytes,
        bool]`。
        """

        ...


class RawInputStreamFactory(Protocol):
    """类契约说明.

    职责: 声明 RawInputStreamFactory
    协议接口,约束实现方必须提供的行为。
    契约: 方法: __call__。
    """

    def __call__(self, device: CaptureDevice) -> RawInputStream:
        """函数契约说明.

        功能: 执行 __call__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        契约: 同步调用。 返回 `RawInputStream`。
        """

        ...


def open_raw_input_stream(device: CaptureDevice) -> RawInputStream:
    """函数契约说明.

    功能: 执行 open_raw_input_stream
    的同步逻辑,并协调
    _SounddeviceRawInputStream。
    参数: device: CaptureDevice。 必填。
    契约: 同步调用。 返回 `RawInputStream`。
    """

    return _SounddeviceRawInputStream(device)


class _SounddeviceRawInputStream:
    """类契约说明.

    职责: 定义 _SounddeviceRawInputStream
    的状态、行为和对外协作边界。
    契约: 方法:
    __init__、__enter__、__exit__、read。
    """

    __slots__ = ("_stream",)

    def __init__(self, device: CaptureDevice) -> None:
        """函数契约说明.

        功能: 初始化
        _SounddeviceRawInputStream
        的字段并建立实例不变式。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._stream = sounddevice.RawInputStream(
            samplerate=int(PCM16_MONO_SAMPLE_RATE),
            channels=int(PCM16_MONO_CHANNELS),
            dtype="int16",
            blocksize=PCM16_MONO_20MS_FRAME_SAMPLES,
            device=device,
        )

    def __enter__(self) -> Self:
        """函数契约说明.

        功能: 执行 __enter__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `Self`。
        """

        self._stream.__enter__()

        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """函数契约说明.

        功能: 执行 __exit__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 exception_type:
        type[BaseException] | None。 必填。
        exception: BaseException | None。
        必填。 traceback: TracebackType |
        None。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._stream.__exit__(exception_type, exception, traceback)

    def read(self, frames: int) -> tuple[bytes, bool]:
        """函数契约说明.

        功能: 执行 read 的同步逻辑,并协调 read,
        bytes。
        参数: self 表示当前实例。 frames: int。
        必填。
        契约: 同步调用。 返回 `tuple[bytes,
        bool]`。
        """

        payload, overflowed = self._stream.read(frames)

        return bytes(payload), overflowed


class PortAudioCaptureSource:
    """类契约说明.

    职责: 定义 PortAudioCaptureSource
    的状态、行为和对外协作边界。
    契约: 方法: __init__、capture_and_send。
    """

    __slots__ = ("_byteorder", "_device", "_stream_factory")

    def __init__(
        self,
        device: CaptureDevice,
        stream_factory: RawInputStreamFactory = open_raw_input_stream,
        byteorder: HostByteOrder = DEFAULT_HOST_BYTEORDER,
    ) -> None:
        """函数契约说明.

        功能: 初始化 PortAudioCaptureSource
        的字段并建立实例不变式。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        stream_factory:
        RawInputStreamFactory。 可省略。
        byteorder: HostByteOrder。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        self._device = device

        self._stream_factory = stream_factory

        self._byteorder: HostByteOrder = byteorder

    def capture_and_send(
        self, boundary: AudioFrameBoundary, sink: AudioRtpSink
    ) -> AudioFrame | None:
        """函数契约说明.

        功能: 执行 capture_and_send
        的同步逻辑,并协调 _normalize_pcm16le,
        AudioFrame, send_audio_frame,
        _stream_factory。
        参数: self 表示当前实例。 boundary:
        AudioFrameBoundary。 必填。 sink:
        AudioRtpSink。 必填。
        契约: 同步调用。 返回 `AudioFrame |
        None`。
        """

        with self._stream_factory(self._device) as stream:
            payload, _overflowed = stream.read(PCM16_MONO_20MS_FRAME_SAMPLES)

        canonical_payload = _normalize_pcm16le(payload, self._byteorder)

        if len(canonical_payload) != PCM16_MONO_20MS_FRAME_BYTES:
            return None

        frame = AudioFrame(
            metadata=AudioMetadata(
                seq=FrameSeq(1),
                sample_rate=PCM16_MONO_SAMPLE_RATE,
                channels=PCM16_MONO_CHANNELS,
                codec=PCM16_CODEC,
                duration_ms=DEFAULT_CHUNK_DURATION_MS,
                byte_length=PCM16_MONO_20MS_FRAME_BYTES,
            ),
            payload=canonical_payload,
        )

        boundary.send_audio_frame(sink, frame)

        return frame


class PortAudioBlockCapture:
    """类契约说明.

    职责: 定义 PortAudioBlockCapture
    的状态、行为和对外协作边界。
    契约: 方法: __init__、open、read_block、acl
    ose、_open_stream。
    """

    __slots__ = ("_byteorder", "_device", "_stream", "_stream_factory")

    def __init__(
        self,
        device: CaptureDevice,
        stream_factory: RawInputStreamFactory = open_raw_input_stream,
        byteorder: HostByteOrder = DEFAULT_HOST_BYTEORDER,
    ) -> None:
        """函数契约说明.

        功能: 初始化 PortAudioBlockCapture
        的字段并建立实例不变式。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        stream_factory:
        RawInputStreamFactory。 可省略。
        byteorder: HostByteOrder。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        self._device = device

        self._stream_factory = stream_factory

        self._byteorder: HostByteOrder = byteorder

        self._stream: RawInputStream | None = None

    async def open(self) -> None:
        """函数契约说明.

        功能: 执行 open 的异步逻辑,并协调 to_thread。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        self._stream = await asyncio.to_thread(self._open_stream)

    async def read_block(self) -> bytes | None:
        """函数契约说明.

        功能: 执行 read_block 的异步逻辑,并协调
        _normalize_pcm16le,
        CaptureStateError, to_thread,
        len。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `bytes | None`。 可能抛出
        CaptureStateError。
        """

        stream = self._stream

        if stream is None:
            raise CaptureStateError()

        payload, _overflowed = await asyncio.to_thread(
            stream.read, PCM16_MONO_20MS_FRAME_SAMPLES
        )

        canonical_payload = _normalize_pcm16le(payload, self._byteorder)

        if len(canonical_payload) != PCM16_MONO_20MS_FRAME_BYTES:
            return None

        return canonical_payload

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并协调
        to_thread。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        stream = self._stream

        if stream is not None:
            self._stream = None

            await asyncio.to_thread(stream.__exit__, None, None, None)

    def _open_stream(self) -> RawInputStream:
        """函数契约说明.

        功能: 执行 _open_stream 的同步逻辑,并协调
        _stream_factory。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `RawInputStream`。
        """

        stream = self._stream_factory(self._device)

        stream.__enter__()

        return stream


def _normalize_pcm16le(payload: bytes, byteorder: HostByteOrder) -> bytes:
    """函数契约说明.

    功能: 执行 _normalize_pcm16le 的同步逻辑,并协调
    join, range, len。
    参数: payload: bytes。 必填。 byteorder:
    HostByteOrder。 必填。
    契约: 同步调用。 返回 `bytes`。
    """

    if byteorder == "little":
        return payload

    return b"".join(
        payload[index : index + 2][::-1] for index in range(0, len(payload), 2)
    )
