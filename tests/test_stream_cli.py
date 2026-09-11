import asyncio

from mic.config import OrchestratorWsUrl, ServiceConfig
from mic.stream_cli import run_stream
from mic.streaming import StreamingRuntimeConfig


def test_run_stream_is_control_only_and_never_constructs_udp(monkeypatch) -> None:
    config = StreamingRuntimeConfig(
        stream_id="mic-primary",
        start_timestamp=96_000,
        max_blocks=1,
        service_config=ServiceConfig(
            OrchestratorWsUrl("wss://orchestrator.example.test/control"),
            asr_endpoint="https://asr.example.test/v1",
            asr_model="asr",
        ),
    )
    calls: list[object] = []

    class Control:
        async def register_input(self, stream_id: str) -> int:
            calls.append(("register", stream_id))
            return 1

        async def wait_closed(self) -> None:
            await asyncio.Future[None]()

        async def aclose(self) -> None:
            calls.append("control_closed")

    class Capture:
        def __init__(self, *, device: object) -> None:
            _ = device

        async def open(self) -> None:
            calls.append("capture_open")

        async def read_block(self) -> bytes | None:
            return None

        async def aclose(self) -> None:
            calls.append("capture_closed")

    class Processor:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def push_enhanced_frame(self, frame: bytes, timestamp: int) -> object:
            raise AssertionError((frame, timestamp))

        def flush_enhanced_frames(self) -> None:
            calls.append("processor_flush")

        async def recognize_endpoint(self, endpoint: object) -> None:
            raise AssertionError(endpoint)

    async def open_control(*args, **kwargs) -> Control:
        _ = args, kwargs
        return Control()

    monkeypatch.setattr("mic.stream_cli.load_streaming_runtime_config", lambda: config)
    monkeypatch.setattr("mic.stream_cli.WebSocketStreamingControl.open", open_control)
    monkeypatch.setattr("mic.stream_cli.PortAudioBlockCapture", Capture)
    monkeypatch.setattr("mic.stream_cli.MicAsrEndpointProcessor", Processor)

    assert asyncio.run(run_stream()) == 0
    assert calls == [
        ("register", "mic-primary"),
        "capture_open",
        "processor_flush",
        "capture_closed",
        "control_closed",
    ]


def test_run_stream_stops_capture_when_control_connection_closes(monkeypatch) -> None:
    config = StreamingRuntimeConfig(
        stream_id="mic-primary",
        start_timestamp=96_000,
        max_blocks=None,
        service_config=ServiceConfig(
            OrchestratorWsUrl("wss://orchestrator.example.test/control"),
            asr_endpoint="https://asr.example.test/v1",
            asr_model="asr",
        ),
    )
    calls: list[object] = []
    capture_started = asyncio.Event()

    class Control:
        async def register_input(self, stream_id: str) -> int:
            calls.append(("register", stream_id))
            return 1

        async def wait_closed(self) -> None:
            await capture_started.wait()

        async def aclose(self) -> None:
            calls.append("control_closed")

    class Capture:
        def __init__(self, *, device: object) -> None:
            _ = device

        async def open(self) -> None:
            calls.append("capture_open")

        async def read_block(self) -> bytes | None:
            capture_started.set()
            await asyncio.Future[bytes]()

        async def aclose(self) -> None:
            calls.append("capture_closed")

    class Processor:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def flush_enhanced_frames(self) -> None:
            calls.append("processor_flush")

    async def open_control(*args, **kwargs) -> Control:
        _ = args, kwargs
        return Control()

    monkeypatch.setattr("mic.stream_cli.load_streaming_runtime_config", lambda: config)
    monkeypatch.setattr("mic.stream_cli.WebSocketStreamingControl.open", open_control)
    monkeypatch.setattr("mic.stream_cli.PortAudioBlockCapture", Capture)
    monkeypatch.setattr("mic.stream_cli.MicAsrEndpointProcessor", Processor)

    assert asyncio.run(run_stream()) == 0
    assert calls == [
        ("register", "mic-primary"),
        "capture_open",
        "capture_closed",
        "control_closed",
    ]


def test_connection_cancellation_stops_pipeline_before_closing_capture(monkeypatch) -> None:
    from mic.stream_cli import _run_connection

    async def scenario() -> None:
        started, stopped = asyncio.Event(), asyncio.Event()

        async def pipeline(*args, **kwargs):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        class Capture:
            closed = False

            async def open(self):
                pass

            async def aclose(self):
                assert stopped.is_set()
                self.closed = True

        class Control:
            async def wait_closed(self):
                await asyncio.Future()

        monkeypatch.setattr("mic.stream_cli.run_continuous_pipeline", pipeline)
        capture = Capture()
        task = asyncio.create_task(_run_connection(
            capture=capture, processor=None, control=Control(), start_timestamp=0,
            enhancer_model=None, enhancer_window_ms=500, camplusplus=None,
            session_id="test",
        ))
        await started.wait()
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task
        assert capture.closed

    asyncio.run(scenario())
