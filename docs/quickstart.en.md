# Quickstart

Use Python 3.12 or later. From this repository, run:

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

Tests do not require a microphone device, GPU, or credentials. For a deployed stream, configure the variables in `.env.example`, including the Orchestrator WSS control URL, trusted-LAN bearer token, Orchestrator UDP RTP ingress, local UDP bind, stream ID, RTP timestamp, trace ID, and session ID. Production requires `wss://` and `TRUSTED_LAN_TOKEN`. `ws://` is allowed only for an explicit loopback test with `MIC_ALLOW_LOOPBACK_WS=true`.

Run `uv run mic-stream` only after those deployment values are present. It binds UDP, registers the source over WSS, waits for `media.rtp.source.ready`, and sends one V2/PT96/L16 RTP packet per complete 16 kHz mono capture block. Leave `MIC_MAX_CAPTURE_BLOCKS` unset for continuous capture, or set it to a positive integer for a bounded verification run.

For the onsite spoken-dialogue loop, use the same `BITNP_SESSION_ID` and `BITNP_MIC_RTP_STREAM_ID` configured on Sound, and use the exact `/control` WSS URL. Start Orchestrator, then Sound, then Mic. Mic remains strategy-agnostic and never has a direct Sound endpoint.
