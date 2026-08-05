import asyncio
import contextlib
import logging
import os
import random

from websockets.exceptions import ConnectionClosed

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

_RECONNECT_DELAYS = (0.5, 1.0, 2.0, 4.0, 8.0, 10.0)


async def run_stream() -> int:
    config = load_streaming_runtime_config()
    service_config = config.service_config
    if service_config is None:
        raise ConfigError(
            key="ORCHESTRATOR_WS_URL", reason="must be configured for WSS control"
        )

    if service_config.asr_endpoint is None or service_config.asr_model is None:
        raise ConfigError(key="MIC_ASR_ENDPOINT", reason="endpoint and model required")
    asr = OpenAICompatibleAsr(
        service_config.asr_endpoint,
        service_config.asr_model,
        service_config.asr_api_key,
    )
    camplusplus = (
        CamPlusPlusOnnx(
            service_config.campp_model_path,
            service_config.campp_model_revision,
            service_config.campp_fbank_config_path,
        )
        if service_config.enable_campp
        else None
    )
    vad = (
        SileroVadOnnx.load(service_config.vad_model_path)
        if service_config.enable_silero_vad
        else None
    )
    enhancer_model = (
        ZipEnhancerOnnx(service_config.zipenhancer_model_path)
        if service_config.enable_zipenhancer
        else None
    )
    attempt = 0
    try:
        while True:
            control: WebSocketStreamingControl | None = None
            reconnect = False
            try:
                control = await WebSocketStreamingControl.open(
                    service_config,
                    ControlContext(
                        trace_id=config.trace_id,
                        session_id=config.session_id,
                    ),
                )
                input_epoch = await control.register_input(config.stream_id)
                attempt = 0
                if vad is not None:
                    vad.reset()
                processor = MicAsrEndpointProcessor(
                    control,
                    stream_id=config.stream_id,
                    asr=asr,
                    vad=vad,
                    asr_endpoint_includes_vad=(
                        service_config.asr_endpoint_includes_vad
                    ),
                    cancellation_epoch=input_epoch,
                )
                reconnect = await _run_connection(
                    capture=PortAudioBlockCapture(device=config.device),
                    processor=processor,
                    control=control,
                    start_timestamp=config.start_timestamp,
                    enhancer_model=enhancer_model,
                    enhancer_window_ms=service_config.zipenhancer_window_ms,
                    camplusplus=camplusplus,
                    session_id=config.session_id,
                )
            except (ConnectionClosed, OSError, TimeoutError):
                reconnect = True
                logging.getLogger(__name__).exception(
                    "mic_connection_failed session=%s outcome=reconnect",
                    config.session_id,
                )
            finally:
                if control is not None:
                    await control.aclose()
            if not reconnect:
                return 0
            delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay * random.uniform(0.8, 1.2))
    finally:
        await asr.aclose()


async def _run_connection(
    *,
    capture: PortAudioBlockCapture,
    processor: MicAsrEndpointProcessor,
    control: WebSocketStreamingControl,
    start_timestamp: int,
    enhancer_model: ZipEnhancerOnnx | None,
    enhancer_window_ms: int,
    camplusplus: CamPlusPlusOnnx | None,
    session_id: str,
) -> bool:
    await capture.open()
    try:
        enhancer = (
            ZipEnhancerStreamingProcessor(
                enhancer_model,
                window_ms=enhancer_window_ms,
            )
            if enhancer_model is not None
            else None
        )
        pipeline_task = asyncio.create_task(
            run_continuous_pipeline(
                capture,
                processor,
                start_timestamp=start_timestamp,
                enhancer=enhancer,
                campp_streamer=(
                    CamPlusPlusStreamingProcessor()
                    if camplusplus is not None
                    else None
                ),
                campp_model=camplusplus,
            )
        )
        control_closed_task = asyncio.create_task(control.wait_closed())
        try:
            done, _ = await asyncio.wait(
                (pipeline_task, control_closed_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if pipeline_task in done:
                await pipeline_task
            else:
                await control_closed_task
                logging.getLogger(__name__).info(
                    "mic_control_disconnected session=%s; stopping capture",
                    session_id,
                )
                pipeline_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pipeline_task
        finally:
            control_closed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await control_closed_task
    finally:
        await capture.aclose()
    return bool(getattr(control, "should_reconnect", False))


def main() -> int:
    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("BITNP_LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return asyncio.run(run_stream())
