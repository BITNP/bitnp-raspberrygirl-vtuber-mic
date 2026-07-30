
from collections.abc import Mapping

import pytest

from mic.config import ConfigError, PEER_WS_URL_KEYS, load_config


def test_load_config_targets_orchestrator_when_required_url_present() -> None:

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}

    config = load_config(env)

    assert config.orchestrator_ws_url == "ws://orchestrator.local/ws"


@pytest.mark.parametrize("peer_url_key", PEER_WS_URL_KEYS)
def test_load_config_rejects_every_peer_websocket_url(peer_url_key: str) -> None:

    env: Mapping[str, str] = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        peer_url_key: "ws://peer.local/ws",
    }

    with pytest.raises(ConfigError, match=peer_url_key):
        load_config(env)


def test_load_config_rejects_non_websocket_orchestrator_url() -> None:

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "http://orchestrator.local/ws"}

    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        load_config(env)
