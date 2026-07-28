# Protocol Subset

Mic is a hub client, not a peer service. Set `ORCHESTRATOR_REPO` to an Orchestrator checkout and read the canonical contracts at `$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` and `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`. Mic does not copy schemas or fixtures.

`mic-stream` connects only to Orchestrator. It sends `media.rtp.source.register` over authenticated WSS with its stream ID, fixed Mic SSRC, L16 codec details, and configured Orchestrator RTP ingress. It must receive the matching `media.rtp.source.ready` event before sending UDP media. Each RTP packet is V2/PT96/L16 at 16 kHz mono with 320 samples per frame. Production control requires WSS and `TRUSTED_LAN_TOKEN`; plain `ws://` is restricted to explicit loopback tests with `MIC_ALLOW_LOOPBACK_WS=true`.
