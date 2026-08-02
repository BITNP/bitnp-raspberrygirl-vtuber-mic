
from collections.abc import Mapping
from pathlib import Path

import pytest

from mic.config import PEER_WS_URL_KEYS, ConfigError, load_config


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


def test_load_config_reads_optional_speech_models_and_endpoint_vad() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws",
            "MIC_ZIPENHANCER_MODEL_PATH": "/models/zipenhancer.onnx",
            "MIC_VAD_MODEL_PATH": "/models/silero.onnx",
            "MIC_ASR_ENDPOINT_INCLUDES_VAD": "true",
        }
    )

    assert config.zipenhancer_model_path == Path("/models/zipenhancer.onnx")
    assert config.zipenhancer_window_ms == 500
    assert config.vad_model_path == Path("/models/silero.onnx")
    assert config.asr_endpoint_includes_vad is True


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
