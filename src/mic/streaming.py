import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlparse

from mic.config import ConfigError, ServiceConfig, load_config
from mic.portaudio_capture import CaptureDevice

MIC_STREAM_ID_KEY: Final = "BITNP_MIC_STREAM_ID"
RTP_TIMESTAMP_KEY: Final = "BITNP_MIC_RTP_TIMESTAMP"
MIC_ALLOW_LOOPBACK_WS_KEY: Final = "MIC_ALLOW_LOOPBACK_WS"
MAX_CAPTURE_BLOCKS_KEY: Final = "MIC_MAX_CAPTURE_BLOCKS"
CAPTURE_DEVICE_KEY: Final = "BITNP_CAPTURE_DEVICE"
TRACE_ID_KEY: Final = "BITNP_TRACE_ID"
SESSION_ID_KEY: Final = "BITNP_SESSION_ID"
FRAME_SAMPLES: Final = 320
PCM16_FRAME_BYTES: Final = FRAME_SAMPLES * 2
FRAME_LOG_INTERVAL: Final = 100
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StreamingRuntimeConfig:
    """Configuration for Mic's local PCM-to-control-plane input pipeline."""

    stream_id: str
    start_timestamp: int
    max_blocks: int | None
    service_config: ServiceConfig | None = None
    device: CaptureDevice = None
    trace_id: str = "mic-stream"
    session_id: str = "mic-stream"


class BlockCapture(Protocol):
    async def open(self) -> None: ...

    async def read_block(self) -> bytes | None: ...

    async def aclose(self) -> None: ...


class StreamingControl(Protocol):
    async def register_input(self, stream_id: str) -> int: ...

    async def aclose(self) -> None: ...


class EndpointProcessor(Protocol):
    async def push(self, frame: bytes, rtp_timestamp: int) -> None: ...

    async def flush(self) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StreamResources:
    capture: BlockCapture
    control: StreamingControl
    endpoint_processor: EndpointProcessor | None = None


class StreamRuntime:
    """Owns capture and local endpoint processing; it never opens an RTP socket."""

    __slots__ = ("_config", "_resources")

    def __init__(self, config: StreamingRuntimeConfig, resources: StreamResources) -> None:
        self._config = config
        self._resources = resources

    async def run(self) -> None:
        await self._resources.control.register_input(self._config.stream_id)
        _LOGGER.debug("mic_control_sent event=mic.input.register stream=%s", self._config.stream_id)
        try:
            await self._resources.capture.open()
            await self._process_capture_blocks()
        finally:
            endpoint_processor = self._resources.endpoint_processor
            if endpoint_processor is not None:
                await endpoint_processor.flush()
                await endpoint_processor.aclose()
            await self._resources.capture.aclose()
            await self._resources.control.aclose()

    async def _process_capture_blocks(self) -> None:
        timestamp = self._config.start_timestamp
        processed_blocks = 0
        while self._config.max_blocks is None or processed_blocks < self._config.max_blocks:
            block = await self._resources.capture.read_block()
            if block is None:
                return
            if len(block) != PCM16_FRAME_BYTES:
                raise ConfigError(key="capture.block", reason="must contain exactly 640 PCM16 bytes")
            endpoint_processor = self._resources.endpoint_processor
            if endpoint_processor is not None:
                await endpoint_processor.push(block, timestamp)
            timestamp = (timestamp + FRAME_SAMPLES) % (1 << 32)
            processed_blocks += 1
            if processed_blocks % FRAME_LOG_INTERVAL == 0:
                _LOGGER.debug(
                    "mic_pcm_processed stream=%s frames=%d frame_bytes=%d",
                    self._config.stream_id,
                    processed_blocks,
                    len(block),
                )


def load_streaming_runtime_config(env: Mapping[str, str] | None = None) -> StreamingRuntimeConfig:
    source = os.environ if env is None else env
    service_config = load_config(source)
    _enforce_control_security(service_config, source)
    return StreamingRuntimeConfig(
        stream_id=_required_text(source, MIC_STREAM_ID_KEY),
        start_timestamp=_unsigned_timestamp(source),
        max_blocks=_max_blocks(source),
        service_config=service_config,
        device=_capture_device(source),
        trace_id=_required_text(source, TRACE_ID_KEY),
        session_id=_required_text(source, SESSION_ID_KEY),
    )


def _enforce_control_security(config: ServiceConfig, env: Mapping[str, str]) -> None:
    parsed = urlparse(config.orchestrator_ws_url)
    if parsed.scheme == "ws" and not _insecure_ws_allowed(env):
        raise ConfigError(
            key="ORCHESTRATOR_WS_URL",
            reason="must use WSS unless trusted-LAN insecure WS is explicitly enabled",
        )
    if config.trusted_lan_token is None:
        raise ConfigError(
            key="TRUSTED_LAN_TOKEN",
            reason="must be configured for Orchestrator control",
        )


def _insecure_ws_allowed(env: Mapping[str, str]) -> bool:
    value = env.get(MIC_ALLOW_LOOPBACK_WS_KEY, "false").strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConfigError(key=MIC_ALLOW_LOOPBACK_WS_KEY, reason="must be true or false")


def _required_text(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if value == "":
        raise ConfigError(key=key, reason="must be configured")
    return value


def _unsigned_timestamp(env: Mapping[str, str]) -> int:
    value = _required_text(env, RTP_TIMESTAMP_KEY)
    if not value.isdecimal() or int(value) >= 1 << 32:
        raise ConfigError(key=RTP_TIMESTAMP_KEY, reason="must be an unsigned 32-bit integer")
    return int(value)


def _max_blocks(env: Mapping[str, str]) -> int | None:
    value = env.get(MAX_CAPTURE_BLOCKS_KEY, "").strip()
    if value == "":
        return None
    if not value.isdecimal() or int(value) == 0:
        raise ConfigError(key=MAX_CAPTURE_BLOCKS_KEY, reason="must be a positive integer when configured")
    return int(value)


def _capture_device(env: Mapping[str, str]) -> CaptureDevice:
    value = env.get(CAPTURE_DEVICE_KEY, "").strip()
    if value == "" or value == "default":
        return None
    if value.isdecimal():
        return int(value)
    return value
