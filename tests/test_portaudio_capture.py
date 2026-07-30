"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import pytest

from mic.portaudio_capture import CaptureDevice, PortAudioCaptureSource, RawInputStream


@dataclass(slots=True)
class FakeRawInputStream:
    """类契约说明.

    职责: 保存 FakeRawInputStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: data、overflowed、read_error、r
    ead_sizes、entered、exited。 方法:
    __enter__、__exit__、read。
    """

    data: bytes

    overflowed: bool = False

    read_error: RuntimeError | None = None

    read_sizes: list[int] = field(default_factory=list)

    entered: bool = False

    exited: bool = False

    def __enter__(self) -> Self:
        """函数契约说明.

        功能: 执行 __enter__ 的同步逻辑,并产出
        entered。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `Self`。
        """

        self.entered = True

        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """函数契约说明.

        功能: 执行 __exit__ 的同步逻辑,并产出
        exited。
        参数: self 表示当前实例。 exception_type:
        type[BaseException] | None。 必填。
        exception: BaseException | None。
        必填。 traceback: TracebackType |
        None。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.exited = True

    def read(self, frames: int) -> tuple[bytes, bool]:
        """函数契约说明.

        功能: 执行 read 的同步逻辑,并协调 append。
        参数: self 表示当前实例。 frames: int。
        必填。
        契约: 同步调用。 返回 `tuple[bytes,
        bool]`。
        """

        self.read_sizes.append(frames)

        if self.read_error is not None:
            raise self.read_error

        return self.data, self.overflowed


@dataclass(slots=True)
class FakeRawInputStreamFactory:
    """类契约说明.

    职责: 保存 FakeRawInputStreamFactory
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream、devices。 方法:
    __call__。
    """

    stream: RawInputStream

    devices: list[CaptureDevice] = field(default_factory=list)

    def __call__(self, device: CaptureDevice) -> RawInputStream:
        """函数契约说明.

        功能: 执行 __call__ 的同步逻辑,并协调
        append。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        契约: 同步调用。 返回 `RawInputStream`。
        """

        self.devices.append(device)

        return self.stream


def test_capture_returns_one_exact_pcm16le_frame_when_stream_returns_one_block() -> (
    None
):
    # Given: a stream yields exactly one 20 ms PCM16 mono block.

    """函数契约说明.

    功能: 验证 capture forwards one exact
    pcm16le frame as rtp when stream
    returns one block 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    payload = bytes(range(256)) * 2 + bytes(range(128))

    stream = FakeRawInputStream(data=payload)

    factory = FakeRawInputStreamFactory(stream=stream)

    source = PortAudioCaptureSource(device="Microphone", stream_factory=factory)

    # When: the source captures one fixed-size block.

    frame = source.capture_one()

    # Then: it requests 320 samples and closes the stream.

    assert frame is not None

    assert frame.payload == payload

    assert frame.metadata.byte_length == 640

    assert factory.devices == ["Microphone"]

    assert stream.read_sizes == [320]

    assert stream.entered is True

    assert stream.exited is True


def test_capture_rejects_short_stream_read_without_rtp_delivery() -> None:
    # Given: a stream returns fewer bytes than one 20 ms PCM16 mono block.

    """函数契约说明.

    功能: 验证 capture rejects short stream
    read without rtp delivery
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    stream = FakeRawInputStream(data=b"\x00" * 639)

    source = PortAudioCaptureSource(
        device=None, stream_factory=FakeRawInputStreamFactory(stream=stream)
    )

    # When: capture receives the truncated read.

    frame = source.capture_one()

    # Then: it returns no frame and releases the stream.

    assert frame is None

    assert stream.exited is True


def test_capture_normalizes_big_endian_int16_bytes_before_packetization() -> None:
    # Given: a big-endian host stream yields one frame of native-endian int16 samples.

    """函数契约说明.

    功能: 验证 capture normalizes big endian
    int16 bytes before packetization
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    native_payload = b"\x12\x34" * 320

    stream = FakeRawInputStream(data=native_payload)

    source = PortAudioCaptureSource(
        device=None,
        stream_factory=FakeRawInputStreamFactory(stream=stream),
        byteorder="big",
    )

    # When: the source captures one frame.

    frame = source.capture_one()

    # Then: frame payload is canonical PCM16LE.

    assert frame is not None

    assert frame.payload == b"\x34\x12" * 320


def test_capture_closes_stream_when_read_raises() -> None:
    # Given: the stream fails while the fixed block is being read.

    """函数契约说明.

    功能: 验证 capture closes stream when
    read raises 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。 可能抛出
    RuntimeError。
    """

    stream = FakeRawInputStream(data=b"", read_error=RuntimeError("read failed"))

    source = PortAudioCaptureSource(
        device=None, stream_factory=FakeRawInputStreamFactory(stream=stream)
    )

    # When / Then: the read error propagates after context-managed stream cleanup.

    with pytest.raises(RuntimeError, match="read failed"):
        source.capture_one()

    assert stream.entered is True

    assert stream.exited is True
