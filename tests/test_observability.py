from mic.config import load_config
from mic.observability import latency_metric, queue_metric, trace_headers
from mic.security import trusted_lan_auth_header, trusted_lan_token_is_valid


def test_observability_helpers_emit_traceable_metrics() -> None:
    config = load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"})

    headers = trace_headers(config, trace_id="trace-001", session_id="session-001")
    latency = latency_metric(config, operation="capture", latency_ms=12.5)
    queue = queue_metric(config, queue_name="audio_frames", depth=2)

    assert headers == {"x-trace-id": "trace-001", "x-session-id": "session-001"}
    assert latency.service == "mic"
    assert latency.operation == "capture"
    assert latency.latency_ms == 12.5
    assert queue.service == "mic"
    assert queue.queue_name == "audio_frames"
    assert queue.depth == 2


def test_trusted_lan_token_header_is_optional_and_validated() -> None:
    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
            "TRUSTED_LAN_TOKEN": "placeholder-token-123",
        },
    )

    assert trusted_lan_auth_header(config) == {"authorization": "Bearer placeholder-token-123"}
    assert trusted_lan_token_is_valid(config, "Bearer placeholder-token-123")
    assert not trusted_lan_token_is_valid(config, "Bearer wrong-token")
