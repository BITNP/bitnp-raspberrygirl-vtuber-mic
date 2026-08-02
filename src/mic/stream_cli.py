import asyncio  # noqa: ANYIO_OK - mic-stream requires asyncio UDP transport.
import logging
import os

from mic.asr import OpenAICompatibleAsr
from mic.asr_runtime import MicAsrEndpointProcessor
from mic.camplusplus import CamPlusPlusOnnx, CamPlusPlusStreamingProcessor
from mic.config import ConfigError
from mic.continuous_pipeline import run_continuous_pipeline
from mic.portaudio_capture import PortAudioBlockCapture
from mic.speech_models import (
    SileroVadOnnx,
    ZipEnhancerOnnx,
    ZipEnhancerStreamingProcessor,
)
from mic.stream_control import ControlContext, WebSocketStreamingControl
from mic.streaming import load_streaming_runtime_config


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

    if service_config.asr_endpoint is None or service_config.asr_model is None:
        raise ConfigError(key="MIC_ASR_ENDPOINT", reason="endpoint and model required")
    if len(
        {
            service_config.campp_model_path is None,
            service_config.campp_model_revision is None,
            service_config.campp_fbank_config_path is None,
        }
    ) != 1:
        raise ConfigError(
            key="MIC_CAMPP_MODEL_PATH", reason="model and revision must be configured together"
        )
    camplusplus = (
        None
        if service_config.campp_model_path is None
        else CamPlusPlusOnnx(
            service_config.campp_model_path,
            service_config.campp_model_revision or "",
            service_config.campp_fbank_config_path or service_config.campp_model_path,
        )
    )
    if camplusplus is not None and service_config.vad_model_path is None:
        raise ConfigError(
            key="MIC_VAD_MODEL_PATH", reason="is required when CAM++ is enabled"
        )
    processor = MicAsrEndpointProcessor(
        control,
        stream_id=config.stream_id,
        asr=OpenAICompatibleAsr(
            service_config.asr_endpoint,
            service_config.asr_model,
            service_config.asr_api_key,
        ),
        vad=(
            None
            if service_config.vad_model_path is None
            else SileroVadOnnx.load(service_config.vad_model_path)
        ),
        asr_endpoint_includes_vad=service_config.asr_endpoint_includes_vad,
    )
    capture = PortAudioBlockCapture(device=config.device)
    await control.register_input(config.stream_id)
    await capture.open()
    try:
        enhancer = (
            None
            if service_config.zipenhancer_model_path is None
            else ZipEnhancerStreamingProcessor(
                ZipEnhancerOnnx(service_config.zipenhancer_model_path),
                window_ms=service_config.zipenhancer_window_ms,
            )
        )
        await run_continuous_pipeline(
            capture,
            processor,
            start_timestamp=config.start_timestamp,
            enhancer=enhancer,
            campp_streamer=None if camplusplus is None else CamPlusPlusStreamingProcessor(),
            campp_model=camplusplus,
        )
    finally:
        await capture.aclose()
        await control.aclose()

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
