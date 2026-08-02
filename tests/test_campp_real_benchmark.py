"""Explicit opt-in benchmark; never logs source PCM or embeddings."""

from __future__ import annotations

import os
from pathlib import Path
from statistics import quantiles
from time import perf_counter

import pytest

from mic.camplusplus import CamPlusPlusOnnx, CamPlusPlusStreamingProcessor


@pytest.mark.real_adapter
def test_camplusplus_processes_one_minute_within_window_budget() -> None:
    if os.environ.get("MIC_CAMPP_REAL_BENCHMARK") != "1":
        pytest.skip("set MIC_CAMPP_REAL_BENCHMARK=1 to run the CAM++ benchmark")
    pcm_path = Path(os.environ["MIC_CAMPP_BENCHMARK_PCM_PATH"])
    model_path = Path(os.environ["MIC_CAMPP_MODEL_PATH"])
    fbank_path = Path(os.environ["MIC_CAMPP_FBANK_CONFIG_PATH"])
    revision = os.environ["MIC_CAMPP_MODEL_REVISION"]
    pcm = pcm_path.read_bytes()
    assert len(pcm) >= 16_000 * 2 * 60
    streamer = CamPlusPlusStreamingProcessor()
    model = CamPlusPlusOnnx(model_path, revision, fbank_path)
    elapsed: list[float] = []
    for offset in range(0, 16_000 * 2 * 60, 640):
        for window in streamer.push(pcm[offset : offset + 640], offset // 2, speech=True):
            started = perf_counter()
            _ = model.embed_pcm16le(window.pcm16le)
            elapsed.append((perf_counter() - started) * 1_000)
    assert elapsed
    assert quantiles(elapsed, n=20)[-1] <= 750
