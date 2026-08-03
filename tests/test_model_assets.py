from mic.camplusplus import CamPlusPlusOnnx
from mic.model_assets import (
    CAMPP_FBANK_CONFIG_PATH,
    CAMPP_MODEL_PATH,
    CAMPP_MODEL_REVISION,
    VAD_MODEL_PATH,
    ZIPENHANCER_MODEL_PATH,
)
from mic.speech_models import SileroVadOnnx, ZipEnhancerOnnx


def test_package_integrated_onnx_assets_load_with_campp_external_weights() -> None:
    assert CAMPP_MODEL_PATH.is_file()
    assert CAMPP_MODEL_PATH.with_suffix(".onnx.data").is_file()
    assert CAMPP_FBANK_CONFIG_PATH.is_file()
    assert ZIPENHANCER_MODEL_PATH.is_file()
    assert VAD_MODEL_PATH.is_file()

    _ = CamPlusPlusOnnx(
        CAMPP_MODEL_PATH,
        CAMPP_MODEL_REVISION,
        CAMPP_FBANK_CONFIG_PATH,
    )
    _ = ZipEnhancerOnnx(ZIPENHANCER_MODEL_PATH)
    _ = SileroVadOnnx.load(VAD_MODEL_PATH)
