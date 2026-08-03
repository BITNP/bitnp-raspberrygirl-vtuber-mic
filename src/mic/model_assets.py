"""Resolve controlled ONNX assets distributed with the Mic package."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Final

_MODEL_PACKAGE: Final = "mic.models"

CAMPP_MODEL_PATH: Final = Path(str(files(_MODEL_PACKAGE).joinpath("campp.onnx")))
CAMPP_FBANK_CONFIG_PATH: Final = Path(
    str(files(_MODEL_PACKAGE).joinpath("campp-fbank-config.json"))
)
ZIPENHANCER_MODEL_PATH: Final = Path(
    str(files(_MODEL_PACKAGE).joinpath("zipenhancer.onnx"))
)
VAD_MODEL_PATH: Final = Path(str(files(_MODEL_PACKAGE).joinpath("silero_vad.onnx")))
CAMPP_MODEL_REVISION: Final = "camplusplus-onnx-v1"
