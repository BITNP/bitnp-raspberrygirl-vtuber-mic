from dataclasses import dataclass

from mic.audio import AudioFrame, AudioFrameSink
from mic.config import OrchestratorWsUrl, ServiceConfig


@dataclass(frozen=True, slots=True)
class OrchestratorWebSocketBoundary:
    config: ServiceConfig

    def target_url(self) -> OrchestratorWsUrl:
        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        return "mic WebSocket boundary placeholder targets Orchestrator only"

    def send_audio_frame(self, sink: AudioFrameSink, frame: AudioFrame) -> None:
        sink.receive_audio_frame(frame)
