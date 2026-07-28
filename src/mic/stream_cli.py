import asyncio  # noqa: ANYIO_OK - mic-stream requires asyncio UDP transport.

from mic.config import ConfigError
from mic.portaudio_capture import PortAudioBlockCapture
from mic.stream_control import ControlContext, WebSocketStreamingControl
from mic.streaming import (
    AsyncioUdpSender,
    StreamResources,
    StreamRuntime,
    load_streaming_runtime_config,
)


async def run_stream() -> int:
    config = load_streaming_runtime_config()
    service_config = config.service_config
    if service_config is None:
        raise ConfigError(key="ORCHESTRATOR_WS_URL", reason="must be configured for WSS control")
    control = await WebSocketStreamingControl.open(
        service_config,
        ControlContext(trace_id=config.trace_id, session_id=config.session_id),
    )
    resources = StreamResources(
        capture=PortAudioBlockCapture(device=config.device),
        control=control,
        udp=AsyncioUdpSender(),
    )
    await StreamRuntime(config, resources).run()
    return 0


def main() -> int:
    return asyncio.run(run_stream())
