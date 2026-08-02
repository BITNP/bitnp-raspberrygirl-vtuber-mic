# VTuber Mic Service

Mic 是 Raspberry Girl 的麦克风与语音识别边界。它只连接 Orchestrator：通过 WSS 注册 RTP source，等待 `media.rtp.source.ready`，发送 16 kHz 单声道 L16 RTP，并在本地完成端点检测和 OpenAI-compatible ASR 后通过同一认证 control connection 发送 `asr.partial`、`asr.final` 与可选 `voice.evidence`。它不连接 Sound、Comments 或 Frontend，也不决定业务动作。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
