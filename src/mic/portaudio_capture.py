
import asyncio  # noqa: ANYIO_OK - PortAudio reads run off the asyncio UDP event loop.
import contextlib
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
    AudioMetadata,
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

    def __str__(self) -> str:

        return "PortAudio capture must open before reading"


class RawInputStream(Protocol):

    def __enter__(self) -> Self:

        ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:

        ...

    def read(self, frames: int) -> tuple[bytes, bool]:

        ...


class RawInputStreamFactory(Protocol):

    def __call__(self, device: CaptureDevice) -> RawInputStream:

        ...


def open_raw_input_stream(device: CaptureDevice) -> RawInputStream:

    return _SounddeviceRawInputStream(device)


class _SounddeviceRawInputStream:

    __slots__ = ("_stream",)

    def __init__(self, device: CaptureDevice) -> None:

        self._stream = sounddevice.RawInputStream(
            samplerate=int(PCM16_MONO_SAMPLE_RATE),
            channels=int(PCM16_MONO_CHANNELS),
            dtype="int16",
            blocksize=PCM16_MONO_20MS_FRAME_SAMPLES,
            device=device,
        )

    def __enter__(self) -> Self:

        self._stream.__enter__()

        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:

        self._stream.__exit__(exception_type, exception, traceback)

    def read(self, frames: int) -> tuple[bytes, bool]:

        payload, overflowed = self._stream.read(frames)

        return bytes(payload), overflowed


class PortAudioCaptureSource:

    __slots__ = ("_byteorder", "_device", "_stream_factory")

    def __init__(
        self,
        device: CaptureDevice,
        stream_factory: RawInputStreamFactory = open_raw_input_stream,
        byteorder: HostByteOrder = DEFAULT_HOST_BYTEORDER,
    ) -> None:

        self._device = device

        self._stream_factory = stream_factory

        self._byteorder: HostByteOrder = byteorder

    def capture_one(self) -> AudioFrame | None:

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

        return frame


class PortAudioBlockCapture:

    __slots__ = (
        "_byteorder",
        "_device",
        "_read_task",
        "_stream",
        "_stream_factory",
    )

    def __init__(
        self,
        device: CaptureDevice,
        stream_factory: RawInputStreamFactory = open_raw_input_stream,
        byteorder: HostByteOrder = DEFAULT_HOST_BYTEORDER,
    ) -> None:

        self._device = device

        self._stream_factory = stream_factory

        self._byteorder: HostByteOrder = byteorder

        self._stream: RawInputStream | None = None

        self._read_task: asyncio.Task[tuple[bytes, bool]] | None = None

    async def open(self) -> None:

        self._stream = await asyncio.to_thread(self._open_stream)

    async def read_block(self) -> bytes | None:

        stream = self._stream

        if stream is None:
            raise CaptureStateError()

        read_task = asyncio.create_task(
            asyncio.to_thread(stream.read, PCM16_MONO_20MS_FRAME_SAMPLES)
        )
        self._read_task = read_task
        try:
            payload, _overflowed = await asyncio.shield(read_task)
        except asyncio.CancelledError:
            # A thread cannot be cancelled. Let the bounded 20 ms PortAudio read
            # return before the caller closes the stream during cleanup.
            await _drain_read_task(read_task)
            raise
        finally:
            if read_task.done():
                self._read_task = None

        canonical_payload = _normalize_pcm16le(payload, self._byteorder)

        if len(canonical_payload) != PCM16_MONO_20MS_FRAME_BYTES:
            return None

        return canonical_payload

    async def aclose(self) -> None:

        stream = self._stream

        if stream is not None:
            self._stream = None

            read_task = self._read_task
            if read_task is not None:
                # Teardown may run after a second cancellation (for example,
                # systemd stopping the service). Never close a PortAudio stream
                # while its worker thread is still inside ``read``.
                await _drain_read_task(read_task)
                self._read_task = None

            await asyncio.to_thread(stream.__exit__, None, None, None)

    def _open_stream(self) -> RawInputStream:

        stream = self._stream_factory(self._device)

        stream.__enter__()

        return stream


def _normalize_pcm16le(payload: bytes, byteorder: HostByteOrder) -> bytes:

    if byteorder == "little":
        return payload

    return b"".join(
        payload[index : index + 2][::-1] for index in range(0, len(payload), 2)
    )


async def _drain_read_task(read_task: asyncio.Task[tuple[bytes, bool]]) -> None:

    try:
        with contextlib.suppress(Exception):
            await asyncio.shield(read_task)
    except asyncio.CancelledError:
        # Finish the already-started PortAudio read before allowing teardown to
        # continue. ``shield`` keeps the worker task alive across cancellation.
        with contextlib.suppress(Exception):
            await asyncio.shield(read_task)
        raise
