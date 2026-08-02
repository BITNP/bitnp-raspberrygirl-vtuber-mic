import asyncio
import logging
from typing import cast

from mic.asr import (
    FRAME_BYTES,
    AsrEndpoint,
    EnergyEndpointDetector,
    OpenAICompatibleAsr,
    Recognition,
)
from mic.asr_runtime import MicAsrEndpointProcessor
from mic.stream_control import WebSocketStreamingControl


def test_endpoint_detector_forces_a_bounded_segment_without_silence() -> None:
    detector = EnergyEndpointDetector(max_frames=3)
    frames = [bytes([index]) * FRAME_BYTES for index in range(3)]

    assert detector.push(frames[0], 0, speech=True) is None
    assert detector.push(frames[1], 320, speech=True) is None
    endpoint = detector.push(frames[2], 640, speech=True)

    assert endpoint is not None
    assert endpoint.pcm16le == b"".join(frames)
    assert endpoint.rtp_start_timestamp == 0
    assert endpoint.rtp_end_timestamp == 960


def test_openai_compatible_asr_appends_transcription_path_to_base_url() -> None:
    asr = OpenAICompatibleAsr("https://asr.example.test/v1/", "asr")

    assert asr._endpoint == "https://asr.example.test/v1/audio/transcriptions"


def test_asr_processor_logs_complete_transcript(caplog) -> None:
    class Asr:
        async def transcribe(self, endpoint: AsrEndpoint) -> Recognition:
            assert endpoint.pcm16le == b"\x00" * FRAME_BYTES
            return Recognition(text="请完整记录这段转写", confidence=0.9)

    class Control:
        async def send_asr_final(self, result, *, sequence: int) -> None:
            assert result.text == "请完整记录这段转写"
            assert sequence == 1

    processor = MicAsrEndpointProcessor(
        cast(WebSocketStreamingControl, cast(object, Control())),
        stream_id="mic-primary",
        asr=cast(OpenAICompatibleAsr, cast(object, Asr())),
    )

    with caplog.at_level(logging.DEBUG, logger="mic.asr_runtime"):
        asyncio.run(
            processor.recognize_endpoint(AsrEndpoint(b"\x00" * FRAME_BYTES, 0, 320))
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "mic_asr_response stream=mic-primary text='请完整记录这段转写' confidence=0.9" in messages
    assert "mic_asr_final_sent stream=mic-primary segment=1 text='请完整记录这段转写'" in messages
