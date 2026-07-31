
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
