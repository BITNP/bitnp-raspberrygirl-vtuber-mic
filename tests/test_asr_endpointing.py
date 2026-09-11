import asyncio
import logging
from typing import cast

import httpx

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


def test_openai_compatible_asr_streams_bounded_response_and_validates_confidence() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert b'name="model"' in await request.aread()
        return httpx.Response(
            200,
            json={"text": "  识别成功  ", "confidence": 0.92},
        )

    async def run() -> Recognition:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            asr = OpenAICompatibleAsr(
                "https://asr.example.test/v1", "asr", "secret", client=client
            )
            return await asr.transcribe(AsrEndpoint(b"\0" * FRAME_BYTES, 0, 320))

    assert asyncio.run(run()) == Recognition("识别成功", 0.92)


def test_openai_compatible_asr_discards_oversize_and_bad_confidence() -> None:
    responses = iter(
        (
            httpx.Response(200, content=b"{" + b"x" * 65_536),
            httpx.Response(200, json={"text": "bad", "confidence": 1.1}),
        )
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async def run() -> tuple[Recognition, Recognition]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            asr = OpenAICompatibleAsr(
                "https://asr.example.test/v1", "asr", client=client
            )
            endpoint = AsrEndpoint(b"\0" * FRAME_BYTES, 0, 320)
            return await asr.transcribe(endpoint), await asr.transcribe(endpoint)

    assert asyncio.run(run()) == (Recognition(""), Recognition(""))


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


def test_disabling_silero_preserves_campp_speech_windows() -> None:
    from mic.camplusplus import CamPlusPlusStreamingProcessor

    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            processor = MicAsrEndpointProcessor(
                cast(WebSocketStreamingControl, cast(object, object())),
                stream_id="mic-test",
                asr=OpenAICompatibleAsr("https://asr.example.test/v1", "asr", client=client),
                vad=None,
            )
            campp = CamPlusPlusStreamingProcessor()
            speech = (10000).to_bytes(2, "little", signed=True) * 320
            silence = bytes(FRAME_BYTES)
            windows = []
            for index in range(100):
                analysis = processor.analyze_enhanced_frame(speech, index * 320)
                windows.extend(campp.push(speech, index * 320, speech=analysis.speech))
            assert windows
            assert windows[0].speech_ms == 1500
            for index in range(20):
                analysis = processor.analyze_enhanced_frame(silence, (100 + index) * 320)
                assert not analysis.speech
            assert analysis.endpoint is not None

    asyncio.run(scenario())
