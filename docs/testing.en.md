# Testing

Run `uv sync --locked` once, then run `uv run pytest`. The suite covers replay, RTP packetization, streaming configuration, WSS security policy, and runtime ordering without live audio hardware. Run `ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health` as a local command-surface check. It validates configuration parsing only, not Orchestrator reachability.

For a real deployment check, configure `mic-stream` with the production WSS URL, trusted-LAN bearer token, and Orchestrator UDP ingress. Run `uv run mic-stream`, then verify on Orchestrator that bearer authentication succeeds, `media.rtp.source.register` is accepted, the matching `media.rtp.source.ready` arrives before media, and UDP RTP frames arrive at the configured ingress. Use `MIC_MAX_CAPTURE_BLOCKS` as a positive integer for a bounded run. WSS is mandatory outside an explicit loopback test.

Live capture needs a usable PortAudio input plus the operating system recording permission. Omit `BITNP_CAPTURE_DEVICE` or set it to `default` for the host default, use an index from the device list, or provide a device-name query.
