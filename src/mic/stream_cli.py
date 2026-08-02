import asyncio  # noqa: ANYIO_OK - mic-stream requires asyncio UDP transport.
import logging
import os

from mic.asr import OpenAICompatibleAsr
from mic.asr_runtime import MicAsrEndpointProcessor
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
        raise ConfigError(
            key="ORCHESTRATOR_WS_URL", reason="must be configured for WSS control"
        )

    control = await WebSocketStreamingControl.open(
        service_config,
        ControlContext(trace_id=config.trace_id, session_id=config.session_id),
    )

    endpoint_processor = None
    if service_config.asr_endpoint is not None or service_config.asr_model is not None:
        if service_config.asr_endpoint is None or service_config.asr_model is None:
            raise ConfigError(key="MIC_ASR_ENDPOINT", reason="endpoint and model must be configured together")
        endpoint_processor = MicAsrEndpointProcessor(
            control,
            stream_id=config.stream_id,
            asr=OpenAICompatibleAsr(
                service_config.asr_endpoint,
                service_config.asr_model,
                service_config.asr_api_key,
            ),
        )
    resources = StreamResources(
        capture=PortAudioBlockCapture(device=config.device),
        control=control,
        udp=AsyncioUdpSender(),
        endpoint_processor=endpoint_processor,
    )

    await StreamRuntime(config, resources).run()

    return 0


def main() -> int:
    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("BITNP_LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return asyncio.run(run_stream())
