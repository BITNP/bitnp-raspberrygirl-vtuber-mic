"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from mic.config import ConfigError
from mic.stream_control import ControlContext, WebSocketStreamingControl
from mic.streaming import (
    RtpEndpoint,
    RtpPort,
    SourceRegistration,
    StreamingRuntimeConfig,
    StreamResources,
    StreamRuntime,
)


@dataclass(slots=True)
class _Connection:
    """类契约说明.

    职责: 保存 _Connection
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: messages。 方法:
    recv、send、close。
    """

    messages: list[str]

    async def recv(self) -> str:
        """函数契约说明.

        功能: 执行 recv 的异步逻辑,并协调 pop。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `str`。
        """

        return self.messages.pop(0)

    async def send(self, message: str) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 message: str。
        必填。
        契约: 异步调用。 返回 `None`。
        """

        _ = message

    async def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        return


@dataclass(slots=True)
class _BlockingCapture:
    """类契约说明.

    职责: 保存 _BlockingCapture
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: entered、release、closed。 方法:
    open、read_block、aclose。
    """

    entered: asyncio.Event = field(default_factory=asyncio.Event)

    release: asyncio.Event = field(default_factory=asyncio.Event)

    closed: bool = False

    async def open(self) -> None:
        """函数契约说明.

        功能: 执行 open 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        return

    async def read_block(self) -> bytes | None:
        """函数契约说明.

        功能: 执行 read_block 的异步逻辑,并协调 set,
        wait。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `bytes | None`。
        """

        self.entered.set()

        await self.release.wait()

        return b"\x10\x20" * 320

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并产出 closed。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        self.closed = True


@dataclass(slots=True)
class _StopControl:
    """类契约说明.

    职责: 保存 _StopControl
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: capture、closed。 方法: register
    _source、wait_source_ready、wait_stop、
    aclose。
    """

    capture: _BlockingCapture

    closed: bool = False

    async def register_source(self, registration: SourceRegistration) -> None:
        """函数契约说明.

        功能: 执行 register_source 的异步逻辑,并产出
        _。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 返回 `None`。
        """

        _ = registration

    async def wait_source_ready(self, registration: SourceRegistration) -> None:
        """函数契约说明.

        功能: 执行 wait_source_ready
        的异步逻辑,并产出 _。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 返回 `None`。
        """

        _ = registration

    async def wait_stop(self, registration: SourceRegistration) -> int:
        """函数契约说明.

        功能: 执行 wait_stop 的异步逻辑,并协调 wait。
        参数: self 表示当前实例。 registration:
        SourceRegistration。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `int`。
        """

        _ = registration

        await self.capture.entered.wait()

        return 4

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并产出 closed。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        self.closed = True


@dataclass(slots=True)
class _Udp:
    """类契约说明.

    职责: 保存 _Udp 不可变数据结构,用类型标注表达字段契约。
    契约: 字段: sent、closed。 方法:
    bind、send、aclose。
    """

    sent: list[bytes] = field(default_factory=list)

    closed: bool = False

    async def bind(self, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 执行 bind 的异步逻辑,并产出 _。
        参数: self 表示当前实例。 endpoint:
        RtpEndpoint。 必填。
        契约: 异步调用。 返回 `None`。
        """

        _ = endpoint

    async def send(self, packet: bytes, endpoint: RtpEndpoint) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 packet: bytes。
        必填。 endpoint: RtpEndpoint。 必填。
        契约: 异步调用。 返回 `None`。
        """

        _ = endpoint

        self.sent.append(packet)

    async def aclose(self) -> None:
        """函数契约说明.

        功能: 执行 aclose 的异步逻辑,并产出 closed。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        self.closed = True


def test_websocket_control_accepts_only_current_orchestrator_flush_epoch() -> None:
    """函数契约说明.

    功能: 验证 websocket control accepts
    only current orchestrator flush
    epoch 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    asyncio.run(_flush_epoch_proof())


def test_websocket_control_ignores_sound_flush_before_mic_stop() -> None:
    """函数契约说明.

    功能: 验证 websocket control ignores
    sound flush before mic stop
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    asyncio.run(_flush_is_not_mic_stop_proof())


def test_stream_runtime_gates_a_pending_capture_before_stop_cancels_it() -> None:
    """函数契约说明.

    功能: 验证 stream runtime gates a
    pending capture before stop cancels
    it 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    asyncio.run(_stop_gate_proof())


def test_websocket_control_rejects_malformed_or_foreign_stop() -> None:
    """函数契约说明.

    功能: 验证 websocket control rejects
    malformed or foreign stop
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    asyncio.run(_malformed_stop_proof())


def test_websocket_control_rejects_duplicate_and_lower_stop_epochs() -> None:
    """函数契约说明.

    功能: 验证 websocket control rejects
    duplicate and lower stop epochs
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    asyncio.run(_stale_epoch_proof())


async def _flush_epoch_proof() -> None:
    # Given: an authenticated WSS control connection with a current Mic stop envelope.

    """函数契约说明.

    功能: 执行 _flush_epoch_proof 的异步逻辑,并协调
    SourceRegistration,
    WebSocketStreamingControl,
    RtpEndpoint, _Connection。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(messages=[_stop(stream_id="stream-001", epoch=4)]),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic receives the Orchestrator's current-stream stop.

    epoch = await control.wait_stop(registration)

    # Then: the exact epoch is admitted for immediate local output gating.

    assert epoch == 4


async def _flush_is_not_mic_stop_proof() -> None:
    # Given: Sound's flush and Mic's authenticated stop are separate controls.

    """函数契约说明.

    功能: 执行 _flush_is_not_mic_stop_proof
    的异步逻辑,并协调 SourceRegistration,
    WebSocketStreamingControl,
    RtpEndpoint, _Connection。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _flush(stream_id="stream-001", epoch=4),
                _stop(stream_id="stream-001", epoch=5),
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic waits for its stop after receiving Sound's flush.

    epoch = await control.wait_stop(registration)

    # Then: the flush is ignored and only the Mic stop advances the stop epoch.

    assert epoch == 5


async def _stop_gate_proof() -> None:
    # Given: capture is blocked after opening while authenticated control receives stop epoch four.

    """函数契约说明.

    功能: 执行 _stop_gate_proof 的异步逻辑,并协调
    _BlockingCapture, _StopControl,
    _Udp, StreamRuntime。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

    capture = _BlockingCapture()

    control = _StopControl(capture)

    udp = _Udp()

    runtime = StreamRuntime(
        StreamingRuntimeConfig(
            "stream-001",
            96_000,
            RtpEndpoint("127.0.0.1", RtpPort(5004)),
            RtpEndpoint("0.0.0.0", RtpPort(0)),
            None,
        ),
        StreamResources(capture, control, udp),
    )

    # When: the control stop wins while a capture block is still pending.

    await runtime.run()

    # Then: the stop gate prevents a 640-byte frame from reaching UDP before cleanup.

    assert udp.sent == []

    assert capture.closed is True

    assert control.closed is True

    assert udp.closed is True


async def _malformed_stop_proof() -> None:
    # Given: a control envelope not authenticated as an Orchestrator flush for this session.

    """函数契约说明.

    功能: 执行 _malformed_stop_proof
    的异步逻辑,并协调 SourceRegistration,
    WebSocketStreamingControl,
    RtpEndpoint, _Connection。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _stop(stream_id="stream-001", epoch=4).replace(
                    '"orchestrator"', '"sound"'
                )
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    # When: Mic receives the foreign control frame after source readiness.

    with pytest.raises(ConfigError, match="authenticated"):
        _ = await control.wait_stop(registration)

    # Then: the source never treats untrusted media control as a local stop.

    malformed = WebSocketStreamingControl(
        _Connection(messages=["{"]), ControlContext("trace-001", "session-001")
    )

    with pytest.raises(ConfigError, match="text control event"):
        _ = await malformed.wait_stop(registration)


async def _stale_epoch_proof() -> None:
    """函数契约说明.

    功能: 执行 _stale_epoch_proof 的异步逻辑,并协调
    SourceRegistration,
    WebSocketStreamingControl,
    RtpEndpoint, _Connection。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

    registration = SourceRegistration(
        "stream-001", RtpEndpoint("127.0.0.1", RtpPort(5004))
    )

    control = WebSocketStreamingControl(
        _Connection(
            messages=[
                _stop(stream_id="stream-001", epoch=5),
                _stop(stream_id="stream-001", epoch=5),
                _stop(stream_id="stream-001", epoch=4),
            ]
        ),
        ControlContext("trace-001", "session-001"),
    )

    assert await control.wait_stop(registration) == 5

    with pytest.raises(ConfigError, match="newer"):
        _ = await control.wait_stop(registration)

    with pytest.raises(ConfigError, match="newer"):
        _ = await control.wait_stop(registration)


def _flush(*, stream_id: str, epoch: int) -> str:
    """函数契约说明.

    功能: 执行 _flush 的同步逻辑,并协调
    _control_event。
    参数: stream_id: str。 必填。 epoch: int。
    必填。
    契约: 同步调用。 返回 `str`。
    """

    return _control_event("media.stream.flush", stream_id=stream_id, epoch=epoch)


def _stop(*, stream_id: str, epoch: int) -> str:
    """函数契约说明.

    功能: 执行 _stop 的同步逻辑,并协调
    _control_event。
    参数: stream_id: str。 必填。 epoch: int。
    必填。
    契约: 同步调用。 返回 `str`。
    """

    return _control_event("media.rtp.source.stop", stream_id=stream_id, epoch=epoch)


def _control_event(event_type: str, *, stream_id: str, epoch: int) -> str:
    """函数契约说明.

    功能: 执行 _control_event 的同步逻辑,并协调
    dumps。
    参数: event_type: str。 必填。 stream_id:
    str。 必填。 epoch: int。 必填。
    契约: 同步调用。 返回 `str`。
    """

    return json.dumps(
        {
            "schema_version": "1.0.0",
            "event_type": event_type,
            "event_id": "flush-001",
            "source": "orchestrator",
            "time": "2026-07-30T00:00:00Z",
            "trace_id": "trace-001",
            "session_id": "session-001",
            "turn_id": "turn-001",
            "segment_id": "segment-001",
            "seq": 4,
            "data": {
                "stream_id": stream_id,
                "cancellation_epoch": epoch,
                "request_id": "flush-request-001",
                "target_generated_ssrc": 0x1234_5678,
            },
        }
    )
