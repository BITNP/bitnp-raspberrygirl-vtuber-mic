
import asyncio
import threading
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import pytest

from mic.portaudio_capture import (
    CaptureDevice,
    CaptureOverflowError,
    PortAudioBlockCapture,
    PortAudioCaptureSource,
    RawInputStream,
)


def test_block_capture_surfaces_portaudio_overflow() -> None:
    stream = FakeRawInputStream(data=b"\x00" * 640, overflowed=True)
    capture = PortAudioBlockCapture(
        device="Microphone",
        stream_factory=FakeRawInputStreamFactory(stream),
    )

    async def scenario() -> None:
        await capture.open()
        with pytest.raises(CaptureOverflowError):
            _ = await capture.read_block()
        await capture.aclose()

    asyncio.run(scenario())


@dataclass(slots=True)
class FakeRawInputStream:

    data: bytes

    overflowed: bool = False

    read_error: RuntimeError | None = None

    read_sizes: list[int] = field(default_factory=list)

    entered: bool = False

    exited: bool = False

    def __enter__(self) -> Self:

        self.entered = True

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

        if self.read_error is not None:
            raise self.read_error

        return self.data, self.overflowed


@dataclass(slots=True)
class FakeRawInputStreamFactory:

    stream: RawInputStream

    devices: list[CaptureDevice] = field(default_factory=list)

    def __call__(self, device: CaptureDevice) -> RawInputStream:

        self.devices.append(device)

        return self.stream


def test_capture_returns_one_exact_pcm16le_frame_when_stream_returns_one_block() -> (
    None
):
    # Given: a stream yields exactly one 20 ms PCM16 mono block.


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


    stream = FakeRawInputStream(data=b"", read_error=RuntimeError("read failed"))

    source = PortAudioCaptureSource(
        device=None, stream_factory=FakeRawInputStreamFactory(stream=stream)
    )

    # When / Then: the read error propagates after context-managed stream cleanup.

    with pytest.raises(RuntimeError, match="read failed"):
        source.capture_one()

    assert stream.entered is True

    assert stream.exited is True


def test_block_capture_waits_for_worker_read_before_close_after_second_cancel() -> None:

    asyncio.run(_close_waits_for_cancelled_worker_read())


def test_block_capture_closes_stream_when_close_is_cancelled() -> None:

    asyncio.run(_close_still_releases_stream_after_cancellation())


async def _close_waits_for_cancelled_worker_read() -> None:

    entered_read = threading.Event()
    release_read = threading.Event()
    calls: list[str] = []

    class Stream:

        def __enter__(self) -> Self:

            calls.append("open")

            return self

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:

            _ = exception_type, exception, traceback

            calls.append("close")

        def read(self, frames: int) -> tuple[bytes, bool]:

            assert frames == 320

            entered_read.set()

            assert release_read.wait(timeout=1)

            return b"\x00\x00" * 320, False

    stream = Stream()

    def stream_factory(device: CaptureDevice) -> RawInputStream:

        _ = device

        return stream

    capture = PortAudioBlockCapture(device=None, stream_factory=stream_factory)

    await capture.open()

    read_task = asyncio.create_task(capture.read_block())

    assert await asyncio.to_thread(entered_read.wait, 1)

    read_task.cancel()

    await asyncio.sleep(0)

    read_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await read_task

    close_task = asyncio.create_task(capture.aclose())

    await asyncio.sleep(0)

    assert calls == ["open"]

    release_read.set()

    await close_task

    assert calls == ["open", "close"]


async def _close_still_releases_stream_after_cancellation() -> None:

    entered_read = threading.Event()
    release_read = threading.Event()
    exited_stream = threading.Event()

    class Stream:

        def __enter__(self) -> Self:

            return self

        def __exit__(
            self,
            exception_type: type[BaseException] | None,
            exception: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:

            _ = exception_type, exception, traceback
            exited_stream.set()

        def read(self, frames: int) -> tuple[bytes, bool]:

            assert frames == 320
            entered_read.set()
            assert release_read.wait(timeout=1)
            return b"\x00\x00" * 320, False

    stream = Stream()
    capture = PortAudioBlockCapture(
        device=None, stream_factory=lambda device: stream
    )
    await capture.open()

    read_task = asyncio.create_task(capture.read_block())
    assert await asyncio.to_thread(entered_read.wait, 1)

    close_task = asyncio.create_task(capture.aclose())
    await asyncio.sleep(0)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    release_read.set()
    assert await asyncio.to_thread(exited_stream.wait, 1)
    await capture.aclose()
    assert read_task.done()
