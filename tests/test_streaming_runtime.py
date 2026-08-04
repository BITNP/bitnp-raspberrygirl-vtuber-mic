import asyncio
import logging
from dataclasses import dataclass, field

import pytest

from mic.config import ConfigError
from mic.streaming import (
    StreamingRuntimeConfig,
    StreamResources,
    StreamRuntime,
    load_streaming_runtime_config,
)


@dataclass(slots=True)
class FakeCapture:
    blocks: list[bytes | None]
    reads: int = 0
    opened: bool = False
    closed: bool = False

    async def open(self) -> None:
        self.opened = True

    async def read_block(self) -> bytes | None:
        self.reads += 1
        return self.blocks.pop(0)

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class BlockingCapture:
    entered_read: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False

    async def open(self) -> None:
        return

    async def read_block(self) -> bytes | None:
        self.entered_read.set()
        await self.release.wait()
        return None

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FakeControl:
    registered_streams: list[str] = field(default_factory=list)
    closed: bool = False

    async def register_input(self, stream_id: str) -> None:
        self.registered_streams.append(stream_id)

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FakeProcessor:
    frames: list[tuple[bytes, int]] = field(default_factory=list)
    flushed: bool = False

    async def push(self, frame: bytes, rtp_timestamp: int) -> None:
        self.frames.append((frame, rtp_timestamp))

    async def flush(self) -> None:
        self.flushed = True


def _config(*, max_blocks: int | None = None) -> StreamingRuntimeConfig:
    return StreamingRuntimeConfig("mic-primary", 96_000, max_blocks)


def test_runtime_registers_control_input_before_capture_and_processes_exact_frames() -> None:
    capture = FakeCapture([b"\x10\x20" * 320, b"\x30\x40" * 320, None])
    control = FakeControl()
    processor = FakeProcessor()

    asyncio.run(StreamRuntime(_config(max_blocks=2), StreamResources(capture, control, processor)).run())

    assert control.registered_streams == ["mic-primary"]
    assert processor.frames == [
        (b"\x10\x20" * 320, 96_000),
        (b"\x30\x40" * 320, 96_320),
    ]
    assert processor.flushed is True
    assert capture.closed is True
    assert control.closed is True


@pytest.mark.parametrize("block", [b"\x10\x20" * 319, b"\x10\x20" * 321])
def test_runtime_rejects_capture_blocks_that_are_not_exactly_20ms(block: bytes) -> None:
    capture = FakeCapture([block])
    processor = FakeProcessor()
    with pytest.raises(ConfigError, match="640"):
        asyncio.run(StreamRuntime(_config(max_blocks=1), StreamResources(capture, FakeControl(), processor)).run())
    assert processor.frames == []
    assert processor.flushed is True


def test_runtime_logs_local_pcm_progress_without_rtp(caplog: pytest.LogCaptureFixture) -> None:
    capture = FakeCapture([b"\x10\x20" * 320] * 100)
    with caplog.at_level(logging.DEBUG, logger="mic.streaming"):
        asyncio.run(StreamRuntime(_config(max_blocks=100), StreamResources(capture, FakeControl())).run())
    assert [record.getMessage() for record in caplog.records if record.msg.startswith("mic_pcm_processed")] == [
        "mic_pcm_processed stream=mic-primary frames=100 frame_bytes=640"
    ]


def test_runtime_cancellation_closes_capture_control_and_flushes_processor() -> None:
    capture = BlockingCapture()
    control = FakeControl()
    processor = FakeProcessor()

    async def cancel_running_stream() -> None:
        task = asyncio.create_task(StreamRuntime(_config(), StreamResources(capture, control, processor)).run())
        await capture.entered_read.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_running_stream())
    assert capture.closed is True
    assert control.closed is True
    assert processor.flushed is True


def test_stream_config_requires_wss_except_for_explicit_loopback_ws() -> None:
    base_environment = {
        "ORCHESTRATOR_WS_URL": "ws://127.0.0.1:8765/control",
        "BITNP_MIC_STREAM_ID": "mic-primary",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
        "BITNP_TRACE_ID": "trace-mic-001",
        "BITNP_SESSION_ID": "session-mic-001",
    }
    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        load_streaming_runtime_config(base_environment)
    config = load_streaming_runtime_config({**base_environment, "MIC_ALLOW_LOOPBACK_WS": "true"})
    assert config.stream_id == "mic-primary"
