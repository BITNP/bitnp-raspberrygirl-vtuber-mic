# VTuber Mic Service

Mode-agnostic microphone service for the Raspberry Girl VTuber system. `mic-stream` connects only to Orchestrator: it authenticates with a trusted-LAN bearer token over WSS, binds its local UDP socket, registers the configured RTP route, waits for `media.rtp.source.ready`, then sends RTP only to the configured Orchestrator UDP ingress. Production requires WSS and a token. Plain `ws://` is accepted only for an explicit loopback test with `MIC_ALLOW_LOOPBACK_WS=true`. `mic-capture` is a local one-frame stdout diagnostic, not a deployment transport.

- [English quickstart](docs/quickstart.en.md)
- [简体中文快速开始](docs/quickstart.zh-CN.md)
- [English deployment guide](docs/deployment.en.md)
- [简体中文部署指南](docs/deployment.zh-CN.md)
- [English protocol reference](docs/protocol.en.md)
- [简体中文协议参考](docs/protocol.zh-CN.md)
