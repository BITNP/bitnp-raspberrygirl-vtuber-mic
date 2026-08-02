# Mic 用户文档

Mic 负责把现场麦克风采集到的声音送入 Raspberry Girl 系统。部署入口是 `mic-stream`。

## 功能

- 持续采集固定为 16 kHz、单声道、PCM16 的 20 ms 音频块。
- 通过 WSS 向 Orchestrator 注册 Mic 输入，并仅提交结构化 `asr.final` 与可选 `voice.evidence`；Mic 不发送 UDP RTP。
- 可选本地 ZipEnhancer 降噪和 Silero VAD。Mic 持续采集，ZipEnhancer 每 500 ms（可配置）增强连续 16 kHz PCM 窗口后交给 VAD；VAD 只切分 ASR 语音段，不会停止录音。增强后的段再供 CAM++ 与 ASR 使用。
- 用 `MIC_ASR_ENDPOINT`、`MIC_ASR_MODEL` 和 `MIC_ASR_API_KEY` 配置 OpenAI-compatible ASR；最终文本经认证 control connection 提交为 `asr.final`。
- 提供 `mic-health` 配置健康检查。

## 快速开始

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

## 使用指南

部署时根据 `.env.example` 配置 Orchestrator WSS control URL、`TRUSTED_LAN_TOKEN`、`ORCHESTRATOR_TLS_CA_PATH`、Mic ASR endpoint/model、可选 ZipEnhancer ONNX 路径和 `MIC_ZIPENHANCER_WINDOW_MS`、Silero VAD ONNX 路径、CAM++ 模型及官方 `fbank_config.json`、stream ID、timestamp、trace ID 和 session ID。CAM++ 启用时必须同时配置模型、revision 和 `MIC_CAMPP_FBANK_CONFIG_PATH`；Mic 用 1.5 秒窗口、0.75 秒步进在增强音频上产生临时 voice evidence，不持久化 embedding。ZipEnhancer 必须使用官方导出的 `noisy_mag` / `noisy_pha` 双输入 ONNX，窗口必须为 20 ms 的整数倍，默认 500 ms；Silero 模型必须有 `input`、`state`、`sr` 输入，CAM++ 启用时始终需要本地 Silero VAD。当前 OpenAI-compatible multipart endpoint 不具备客户端流式转写能力。`ORCHESTRATOR_TLS_CA_PATH` 指向只读 PEM CA bundle，用于校验 Orchestrator WSS；Mic 的 ASR HTTPS 信任配置使用部署环境的系统信任库。生产环境必须使用 `wss://` 和 token；`ws://` 只允许在显式设置 `MIC_ALLOW_LOOPBACK_WS=true` 的回环测试中使用。

以实际运行 `mic-stream` 的服务账号验证 `BITNP_CAPTURE_DEVICE`，并在部署后说话与静音各测试一次。错误的默认设备、输出监视器或持续环境噪声会让 Mic 的端点检测不断产生伪片段，进而打断正在播放的回答。PipeWire/PulseAudio 桌面中，systemd 系统服务需要该账号可访问的音频会话；不要假定登录用户的默认音频设备会自动提供给 `bitnp`。

现场讲解链路中，Mic 的 `BITNP_SESSION_ID` 与 `BITNP_MIC_RTP_STREAM_ID` 必须匹配 Orchestrator 已注册的 Mic 输入。Mic 不与 Sound 直连。启动顺序是 Orchestrator、Sound、Mic。
