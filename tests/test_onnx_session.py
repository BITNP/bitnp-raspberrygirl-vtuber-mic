from pathlib import Path

import pytest

from mic.onnx_session import create_session


@pytest.mark.parametrize("cuda", [False, True])
def test_selects_available_provider_and_reports_actual(monkeypatch, caplog, cuda):
    requested = []
    preloads = []
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if cuda else ["CPUExecutionProvider"]

    class Session:
        def __init__(self, path, *, providers):
            requested.append(providers)

        def get_providers(self):
            return ["CPUExecutionProvider"]

    monkeypatch.setattr("mic.onnx_session.onnxruntime.get_available_providers", lambda: providers)
    monkeypatch.setattr("mic.onnx_session.onnxruntime.preload_dlls", lambda **kw: preloads.append(kw))
    monkeypatch.setattr("mic.onnx_session.onnxruntime.InferenceSession", Session)
    with caplog.at_level("INFO"):
        create_session(Path("model.onnx"))
    assert requested == [providers]
    assert preloads == ([{"directory": ""}] if cuda else [])
    assert "providers=['CPUExecutionProvider']" in caplog.text


@pytest.mark.parametrize("failure", ["preload", "initialize"])
def test_cuda_failure_uses_cpu(monkeypatch, failure):
    calls = []

    def preload(**kwargs):
        if failure == "preload":
            raise OSError("missing CUDA library")

    class Session:
        def __init__(self, path, *, providers):
            calls.append(providers)
            if "CUDAExecutionProvider" in providers:
                raise RuntimeError("CUDA initialization failed")

        def get_providers(self):
            return ["CPUExecutionProvider"]

    monkeypatch.setattr("mic.onnx_session.onnxruntime.get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr("mic.onnx_session.onnxruntime.preload_dlls", preload)
    monkeypatch.setattr("mic.onnx_session.onnxruntime.InferenceSession", Session)
    create_session(Path("model.onnx"))
    assert calls[-1] == ["CPUExecutionProvider"]
    assert len(calls) == (1 if failure == "preload" else 2)


def test_invalid_model_is_not_hidden_by_cpu_fallback(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("invalid model")

    monkeypatch.setattr("mic.onnx_session.onnxruntime.get_available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr("mic.onnx_session.onnxruntime.InferenceSession", fail)
    with pytest.raises(RuntimeError, match="invalid model"):
        create_session(Path("invalid.onnx"))
