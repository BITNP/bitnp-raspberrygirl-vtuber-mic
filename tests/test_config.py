
from collections.abc import Mapping
from pathlib import Path

import pytest

from mic.config import PEER_WS_URL_KEYS, ConfigError, load_config
from mic.model_assets import (
    CAMPP_FBANK_CONFIG_PATH,
    CAMPP_MODEL_PATH,
    CAMPP_MODEL_REVISION,
    VAD_MODEL_PATH,
    ZIPENHANCER_MODEL_PATH,
)

ROOT = Path(__file__).resolve().parents[1]


def test_load_config_targets_orchestrator_when_required_url_present() -> None:

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}

    config = load_config(env)

    assert config.orchestrator_ws_url == "ws://orchestrator.local/ws"


@pytest.mark.parametrize(
    "env",
    [
        {"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"},
        {
            "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
            "ORCHESTRATOR_TLS_CA_PATH": "   ",
        },
    ],
)
def test_load_config_uses_no_ca_bundle_when_path_is_absent_or_blank(
    env: Mapping[str, str],
) -> None:
    config = load_config(env)

    assert config.tls_ca_path is None


def test_load_config_uses_configured_ca_bundle_path() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
            "ORCHESTRATOR_TLS_CA_PATH": "/etc/bitnp/internal-ca.pem",
        }
    )

    assert config.tls_ca_path == Path("/etc/bitnp/internal-ca.pem")


def test_load_config_uses_package_integrated_speech_models() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
            "MIC_ASR_ENDPOINT_INCLUDES_VAD": "true",
        }
    )

    assert config.zipenhancer_model_path == ZIPENHANCER_MODEL_PATH
    assert config.campp_model_path == CAMPP_MODEL_PATH
    assert config.campp_model_revision == CAMPP_MODEL_REVISION
    assert config.campp_fbank_config_path == CAMPP_FBANK_CONFIG_PATH
    assert config.zipenhancer_window_ms == 500
    assert config.vad_model_path == VAD_MODEL_PATH
    assert config.asr_endpoint_includes_vad is True
    assert config.enable_zipenhancer is True
    assert config.enable_silero_vad is True
    assert config.enable_campp is True


def test_load_config_can_disable_each_optional_speech_model() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
            "MIC_ENABLE_ZIPENHANCER": "false",
            "MIC_ENABLE_SILERO_VAD": "false",
            "MIC_ENABLE_CAMPP": "false",
        }
    )

    assert config.enable_zipenhancer is False
    assert config.enable_silero_vad is False
    assert config.enable_campp is False


def test_shipped_environment_example_uses_parseable_canonical_mic_keys() -> None:
    values = {
        key: value
        for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
        for key, value in (line.split("=", 1),)
    }

    config = load_config(values)

    assert config.orchestrator_ws_url == "wss://orchestrator.example.test/control"
    assert values["BITNP_MIC_STREAM_ID"] == "onsite-primary"
    assert "BITNP_MIC_RTP_STREAM_ID" not in values


def test_load_config_ignores_legacy_model_path_variables() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
            "MIC_CAMPP_MODEL_PATH": "/models/campp.onnx",
            "MIC_CAMPP_MODEL_REVISION": "legacy",
            "MIC_CAMPP_FBANK_CONFIG_PATH": "/models/campp-fbank-config.json",
            "MIC_ZIPENHANCER_MODEL_PATH": "/models/zipenhancer.onnx",
            "MIC_VAD_MODEL_PATH": "/models/silero.onnx",
        }
    )

    assert config.campp_model_path == CAMPP_MODEL_PATH
    assert config.zipenhancer_model_path == ZIPENHANCER_MODEL_PATH
    assert config.vad_model_path == VAD_MODEL_PATH


def test_load_config_rejects_invalid_endpoint_vad_flag() -> None:
    with pytest.raises(ConfigError, match="MIC_ASR_ENDPOINT_INCLUDES_VAD"):
        load_config(
            {
                "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
                "MIC_ASR_ENDPOINT_INCLUDES_VAD": "yes",
            }
        )


@pytest.mark.parametrize("value", ["21", "0", "not-a-number"])
def test_load_config_rejects_invalid_zipenhancer_window(value: str) -> None:
    with pytest.raises(ConfigError, match="MIC_ZIPENHANCER_WINDOW_MS"):
        load_config(
            {
                "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
                "MIC_ZIPENHANCER_WINDOW_MS": value,
            }
        )


@pytest.mark.parametrize("peer_url_key", PEER_WS_URL_KEYS)
def test_load_config_rejects_every_peer_websocket_url(peer_url_key: str) -> None:

    env: Mapping[str, str] = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "ORCHESTRATOR_TLS_CA_PATH": "/etc/bitnp/internal-ca.pem",
        peer_url_key: "ws://peer.local/ws",
    }

    with pytest.raises(ConfigError, match=peer_url_key):
        load_config(env)


def test_load_config_rejects_non_websocket_orchestrator_url() -> None:

    env: Mapping[str, str] = {
        "ORCHESTRATOR_WS_URL": "http://orchestrator.local/ws",
        "ORCHESTRATOR_TLS_CA_PATH": "/etc/bitnp/internal-ca.pem",
    }

    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        load_config(env)
