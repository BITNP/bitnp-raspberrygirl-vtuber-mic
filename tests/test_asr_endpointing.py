from mic.asr import FRAME_BYTES, EnergyEndpointDetector, OpenAICompatibleAsr


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
