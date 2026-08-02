import json

import numpy

from mic.campp_fbank import CamppFbank, CamppFbankConfig


def test_official_fbank_config_extracts_mean_normalized_80_bin_features(tmp_path) -> None:
    config_path = tmp_path / "fbank.json"
    config_path.write_text(
        json.dumps(
            {
                "FrameExtractionOptions": {
                    "sample_freq": 16000,
                    "frame_shift_ms": 10.0,
                    "frame_length_ms": 25.0,
                    "dither": 0.0,
                },
                "MelBanksOptions": {"num_bins": 80},
                "use_power": True,
                "use_log_fbank": True,
            }
        ),
        encoding="utf-8",
    )
    samples = (numpy.sin(numpy.arange(24_000) * 0.1) * 10_000).astype("<i2")

    features = CamppFbank(CamppFbankConfig.load(config_path)).extract(samples.tobytes())

    assert features.shape == (148, 80)
    assert numpy.all(numpy.isfinite(features))
    assert numpy.allclose(features.mean(axis=0), 0, atol=1e-5)
