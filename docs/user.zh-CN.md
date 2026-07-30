# Mic 用户文档

Mic 负责把现场麦克风采集到的声音送入 Raspberry Girl 系统。用户只需要关心两类入口：部署入口 `mic-stream` 和本地诊断入口 `mic-capture`。

## 功能

- 采集 16 kHz 单声道音频。
- 将完整 20 ms 音频块封装为 V2/PT96/L16 RTP。
- 通过 WSS 向 Orchestrator 注册音源。
- 在收到匹配的 `media.rtp.source.ready` 后发送 UDP RTP。
- 提供 `mic-health` 配置健康检查和 `mic-capture` 单帧诊断。

## 快速开始

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

## 使用指南

部署时根据 `.env.example` 配置 Orchestrator WSS control URL、`TRUSTED_LAN_TOKEN`、Orchestrator RTP ingress、本地 UDP bind、stream ID、timestamp、trace ID 和 session ID。生产环境必须使用 `wss://` 和 token；`ws://` 只允许在显式设置 `MIC_ALLOW_LOOPBACK_WS=true` 的回环测试中使用。

现场讲解链路中，Mic 的 `BITNP_SESSION_ID` 和 `BITNP_MIC_RTP_STREAM_ID` 必须与 Sound 使用的 session 和 stream 对齐。启动顺序是 Orchestrator、Sound、Mic。

`mic-capture` 只采集一帧并把一个 RTP packet 写到 stdout，用于检查本机 PortAudio 输入和 RTP 封包。它不是部署传输方式。
