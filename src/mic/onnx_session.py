"""Shared CUDA-first ONNX session construction for local speech models."""

from __future__ import annotations

import logging
from pathlib import Path

import onnxruntime

LOGGER = logging.getLogger(__name__)
_CPU = "CPUExecutionProvider"
_CUDA = "CUDAExecutionProvider"


def create_session(path: Path) -> onnxruntime.InferenceSession:
    """Prefer CUDA when supported; retain CPU kernels and initialization fallback."""
    providers = [_CPU]
    if _CUDA in onnxruntime.get_available_providers():
        try:
            # Load the packaged CUDA/cuDNN libraries without requiring Torch.
            onnxruntime.preload_dlls(directory="")
            providers.insert(0, _CUDA)
        except (OSError, RuntimeError):
            LOGGER.info("onnx_provider model=%s outcome=preload_cpu_fallback", path.name)
    try:
        session = onnxruntime.InferenceSession(path, providers=providers)
    except Exception:
        if _CUDA not in providers:
            raise
        LOGGER.info("onnx_provider model=%s outcome=initialization_cpu_fallback", path.name)
        session = onnxruntime.InferenceSession(path, providers=[_CPU])
    # ORT can silently fall back internally when the CUDA provider cannot load.
    actual = session.get_providers()
    LOGGER.info("onnx_provider model=%s providers=%s", path.name, actual)
    LOGGER.debug(
        "onnx_session_created model=%s requested=%s actual=%s outcome=ready",
        path.name, providers, actual,
    )
    return session
