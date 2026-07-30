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

`mic-capture` uses `sounddevice` and PortAudio to read one real audio frame. List the available PortAudio devices and their indexes with:

```bash
uv run python -m sounddevice
```

`BITNP_CAPTURE_DEVICE` is optional. Omit it or set it to `default` for the host default input. Set it to a numeric index from the discovery output, or to a name query such as `Microphone`. `mic-capture` is a local one-frame diagnostic, not a deployment path. It requires a syntactically valid `ORCHESTRATOR_WS_URL` because it shares service configuration, but it does not connect to that URL. It captures exactly 20 ms, 320 samples, and a 640-byte L16 payload, then writes one RTP packet to standard output. `frame.rtp` is only a local artifact.

```bash
BITNP_CAPTURE_DEVICE=default \
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control \
BITNP_MIC_RTP_STREAM_ID=mic-primary \
BITNP_MIC_RTP_TIMESTAMP=0 \
uv run mic-capture > frame.rtp
```
