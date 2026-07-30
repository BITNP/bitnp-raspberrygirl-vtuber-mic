# 快速开始

使用 Python 3.12 或更高版本。在本仓库中运行：

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

测试不需要麦克风设备、GPU 或凭据。部署流时，应配置 `.env.example` 中的变量，包括 Orchestrator WSS 控制 URL、可信局域网 Bearer token、Orchestrator UDP RTP 接入端点、本地 UDP 绑定、流 ID、RTP 时间戳、追踪 ID 和会话 ID。生产环境必须使用 `wss://` 和 `TRUSTED_LAN_TOKEN`。只有在 `MIC_ALLOW_LOOPBACK_WS=true` 的明确回环测试中才允许使用 `ws://`。

只有在上述部署值已经设置后才运行 `uv run mic-stream`。它绑定 UDP，通过 WSS 注册音源，等待 `media.rtp.source.ready`，然后为每个完整的 16 kHz 单声道采集块发送一个 V2/PT96/L16 RTP 数据包。不设置 `MIC_MAX_CAPTURE_BLOCKS` 时会持续采集，将其设为正整数时可进行有限次数的验证运行。

现场语音交互链路中，应使用与 Sound 相同的 `BITNP_SESSION_ID` 和 `BITNP_MIC_RTP_STREAM_ID`，并使用完全一致的 `/control` WSS URL。按 Orchestrator、Sound、Mic 的顺序启动。Mic 保持不感知业务策略，且没有直接 Sound 端点。
