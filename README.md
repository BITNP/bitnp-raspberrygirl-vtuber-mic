# VTuber Mic Service

Mic 是 Raspberry Girl 的模式无关麦克风模块。它只连接 Orchestrator：通过 WSS 注册 RTP source，等待 `media.rtp.source.ready`，再把 16 kHz 单声道 L16 RTP 发送到 Orchestrator UDP ingress。它不连接 Sound、Comments 或 Frontend。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
- [English quickstart](docs/quickstart.en.md)
- [快速开始](docs/quickstart.zh-CN.md)
- [架构](docs/architecture.zh-CN.md)
- [协议](docs/protocol.zh-CN.md)
- [测试](docs/testing.zh-CN.md)
- [部署](docs/deployment.zh-CN.md)
