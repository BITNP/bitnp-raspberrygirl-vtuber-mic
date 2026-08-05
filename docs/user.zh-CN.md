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

部署时根据 `.env.example` 配置 Orchestrator WSS control URL、`TRUSTED_LAN_TOKEN`、`ORCHESTRATOR_TLS_CA_PATH`、Mic ASR endpoint/model、ZipEnhancer 窗口、stream ID、timestamp、trace ID 和 session ID。CAM++、官方 `fbank_config.json`、ZipEnhancer 与 Silero VAD ONNX 已随 Mic 安装包分发；`MIC_ENABLE_ZIPENHANCER`、`MIC_ENABLE_SILERO_VAD`、`MIC_ENABLE_CAMPP` 默认均为 `true`，关闭某项时不会加载相应模型。Mic 用 1.5 秒窗口、0.75 秒步进在增强音频上产生临时 voice evidence，不持久化 embedding。ZipEnhancer 使用官方 `noisy_mag` / `noisy_pha` 双输入 ONNX，窗口必须为 20 ms 的整数倍，默认 500 ms；Silero 模型使用 `input`、`state`、`sr` 输入。当前 OpenAI-compatible multipart endpoint 不具备客户端流式转写能力。`ORCHESTRATOR_TLS_CA_PATH` 指向只读 PEM CA bundle，用于校验 Orchestrator WSS；Mic 的 ASR HTTPS 信任配置使用部署环境的系统信任库。生产环境必须使用 `wss://` 和 token；`ws://` 只允许在显式设置 `MIC_ALLOW_LOOPBACK_WS=true` 的回环测试中使用。

以实际运行 `mic-stream` 的服务账号验证 `BITNP_CAPTURE_DEVICE`，并在部署后说话与静音各测试一次。错误的默认设备、输出监视器或持续环境噪声会让 Mic 的端点检测不断产生伪片段，进而打断正在播放的回答。PipeWire/PulseAudio 桌面中，systemd 系统服务需要该账号可访问的音频会话；不要假定登录用户的默认音频设备会自动提供给 `bitnp`。

现场讲解链路中，Mic 的 `BITNP_SESSION_ID` 与 `BITNP_MIC_STREAM_ID` 必须匹配 Orchestrator 已注册的 Mic 输入。Mic 注册后必须收到含独立 `input_epoch` 的 `mic.input.ready` 才打开采集；该 epoch 同时关联 ASR final 与 voice evidence，不受 Sound 输出 lease 变化影响。控制连接异常断开时 Mic 按 0.5、1、2、4、8、10 秒上限并带 ±20% 抖动重连；配置或模型错误不会重试。PortAudio overflow 会丢弃该帧、推进 20 ms RTP 时间并重置端点/VAD/增强/CAM++ 状态。Mic 不与 Sound 直连，也不建立 RTP 路由。启动顺序是 Orchestrator、Sound、Mic。
