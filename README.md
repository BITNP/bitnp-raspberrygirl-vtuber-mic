# VTuber Mic Service

Mic 是 Raspberry Girl 的策略无关麦克风模块。它只连接 Orchestrator：通过 WSS 注册 RTP source，等待 `media.rtp.source.ready`，再把 16 kHz 单声道 L16 RTP 发送到 Orchestrator UDP ingress。它不连接 Sound、Comments 或 Frontend。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
