from mic.camplusplus import CamPlusPlusStreamingProcessor


def test_camplusplus_streamer_emits_official_overlap_windows() -> None:
    processor = CamPlusPlusStreamingProcessor()
    frame = b"\x01\x00" * 320
    emitted = []

    for index in range(113):
        emitted.extend(processor.push(frame, index * 320, speech=True))

    assert [(window.rtp_start_timestamp, window.rtp_end_timestamp) for window in emitted] == [
        (0, 24_000),
        (12_000, 36_000),
    ]
    assert [window.speech_ms for window in emitted] == [1_500, 1_500]


def test_camplusplus_streamer_requires_one_second_of_speech() -> None:
    processor = CamPlusPlusStreamingProcessor()
    frame = b"\x00" * 640
    emitted = []

    for index in range(75):
        emitted.extend(processor.push(frame, index * 320, speech=index < 49))

    assert emitted == []


def test_camplusplus_streamer_discards_short_tail_on_silence() -> None:
    processor = CamPlusPlusStreamingProcessor()
    frame = b"\x00" * 640

    for index in range(30):
        assert processor.push(frame, index * 320, speech=True) == ()
    for index in range(20):
        assert processor.push(frame, (index + 30) * 320, speech=False) == ()

    assert processor.push(frame, 16_000, speech=True) == ()
