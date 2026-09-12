# VTuber Mic Service

Mic 是树莓娘的麦克风与语音识别边界。它只连接 Orchestrator：通过 WSS 注册 control-only input，在本地持续采集，并依次完成可选 ZipEnhancer 降噪、Silero VAD/端点判断、CAM++ 和 OpenAI-compatible ASR 后，通过同一认证 control connection 发送 `asr.final` 与可选 `voice.evidence`。控制协议支持诊断用 `asr.partial`，当前 endpoint-batched ASR 管线不生成 partial。VAD 只切分 ASR 语音段，不停止录音。Mic 不发送 RTP 音频、不连接 Sound、Comments 或 Frontend，也不决定业务动作。详见[用户文档](docs/user.zh-CN.md)与[开发者文档](docs/developer.zh-CN.md)。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
