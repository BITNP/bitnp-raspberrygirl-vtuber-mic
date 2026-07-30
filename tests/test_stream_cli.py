import asyncio
from dataclasses import dataclass

from mic.config import OrchestratorWsUrl, ServiceConfig
from mic.stream_cli import run_stream
from mic.stream_control import ControlContext
from mic.streaming import RtpEndpoint, RtpPort, StreamResources, StreamingRuntimeConfig


@dataclass(frozen=True, slots=True)
class _Control:
    marker: str = "control"


def test_run_stream_composes_only_production_control_capture_and_udp(
    monkeypatch,
) -> None:
    # Given: a configured Mic stream and isolated production-adapter constructors.
    config = StreamingRuntimeConfig(
        stream_id="mic-primary",
        start_timestamp=96_000,
        rtp_endpoint=RtpEndpoint("orchestrator.example.test", RtpPort(5004)),
        udp_bind_endpoint=RtpEndpoint("0.0.0.0", RtpPort(0)),
        max_blocks=1,
        service_config=ServiceConfig(
            OrchestratorWsUrl("wss://orchestrator.example.test/control")
        ),
    )
    control = _Control()
    captured: list[tuple[ServiceConfig, ControlContext]] = []

    async def open_control(
        service_config: ServiceConfig, context: ControlContext
    ) -> _Control:
        captured.append((service_config, context))
        return control

    class Capture:
        def __init__(self, *, device: object) -> None:
            self.device = device

    class Udp:
        pass

    class Runtime:
        def __init__(
            self, received_config: StreamingRuntimeConfig, resources: StreamResources
        ) -> None:
            assert received_config is config
            self.resources = resources

        async def run(self) -> None:
            assert type(self.resources.capture) is Capture
            assert self.resources.control is control
            assert type(self.resources.udp) is Udp

    monkeypatch.setattr("mic.stream_cli.load_streaming_runtime_config", lambda: config)
    monkeypatch.setattr("mic.stream_cli.WebSocketStreamingControl.open", open_control)
    monkeypatch.setattr("mic.stream_cli.PortAudioBlockCapture", Capture)
    monkeypatch.setattr("mic.stream_cli.AsyncioUdpSender", Udp)
    monkeypatch.setattr("mic.stream_cli.StreamRuntime", Runtime)

    # When: the mic-stream composition root starts.
    exit_code = asyncio.run(run_stream())

    # Then: it wires the configured Orchestrator control into the only streaming runtime.
    assert exit_code == 0
    assert captured[0][0] is config.service_config
