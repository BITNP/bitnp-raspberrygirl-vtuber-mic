# Mic 用户文档

Mic 负责把现场麦克风采集到的声音送入 Raspberry Girl 系统。部署入口是 `mic-stream`。

## 功能

- 采集 16 kHz 单声道音频。
- 将完整 20 ms 音频块封装为 V2/PT96/L16 RTP。
- 通过 WSS 向 Orchestrator 注册音源。
- 在收到匹配的 `media.rtp.source.ready` 后发送 UDP RTP。
- 提供 `mic-health` 配置健康检查。

## 快速开始

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

## 使用指南

部署时根据 `.env.example` 配置 Orchestrator WSS control URL、`TRUSTED_LAN_TOKEN`、`ORCHESTRATOR_TLS_CA_PATH`、Orchestrator RTP ingress、本地 UDP bind、stream ID、timestamp、trace ID 和 session ID。`ORCHESTRATOR_TLS_CA_PATH` 指向只读 PEM CA bundle，它与 Orchestrator、Sound、Comments 共用，可包含内部根证书和中间证书。生产环境必须使用 `wss://` 和 token；`ws://` 只允许在显式设置 `MIC_ALLOW_LOOPBACK_WS=true` 的回环测试中使用。

以实际运行 `mic-stream` 的服务账号验证 `BITNP_CAPTURE_DEVICE`，并在部署后说话与静音各测试一次。错误的默认设备、输出监视器或持续环境噪声会让 Orchestrator 的端点检测不断产生伪片段，进而打断正在播放的回答。PipeWire/PulseAudio 桌面中，systemd 系统服务需要该账号可访问的音频会话；不要假定登录用户的默认音频设备会自动提供给 `bitnp`。

现场讲解链路中，Mic 的 `BITNP_SESSION_ID` 和 `BITNP_MIC_RTP_STREAM_ID` 必须与 Sound 使用的 session 和 stream 对齐。启动顺序是 Orchestrator、Sound、Mic。
