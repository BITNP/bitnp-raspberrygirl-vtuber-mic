# 快速开始

使用 Python 3.12 或更高版本。在本仓库中运行：

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

测试不需要麦克风设备、GPU 或凭据。部署流时，应配置 `.env.example` 中的变量，包括 Orchestrator WSS 控制 URL、可信局域网 Bearer token、Orchestrator UDP RTP 接入端点、本地 UDP 绑定、流 ID、RTP 时间戳、追踪 ID 和会话 ID。生产环境必须使用 `wss://` 和 `TRUSTED_LAN_TOKEN`。只有在 `MIC_ALLOW_LOOPBACK_WS=true` 的明确回环测试中才允许使用 `ws://`。

只有在上述部署值已经设置后才运行 `uv run mic-stream`。它绑定 UDP，通过 WSS 注册音源，等待 `media.rtp.source.ready`，然后为每个完整的 16 kHz 单声道采集块发送一个 V2/PT96/L16 RTP 数据包。不设置 `MIC_MAX_CAPTURE_BLOCKS` 时会持续采集，将其设为正整数时可进行有限次数的验证运行。

现场讲解链路中，应使用与 Sound 相同的 `BITNP_SESSION_ID` 和 `BITNP_MIC_RTP_STREAM_ID`，并使用完全一致的 `/control` WSS URL。按 Orchestrator、Sound、Mic 的顺序启动。Mic 保持 mode-agnostic，且没有直接 Sound 端点。

`mic-capture` 使用 `sounddevice` 和 PortAudio 读取一个真实音频帧。使用以下命令列出可用的 PortAudio 设备及其索引：

```bash
uv run python -m sounddevice
```

`BITNP_CAPTURE_DEVICE` 是可选项。不设置它或将其设为 `default` 时，使用主机默认输入。也可设为设备列表中的数字索引，或名称查询，例如 `Microphone`。`mic-capture` 是本地单帧诊断工具，不是部署路径。由于它共用服务配置，因此需要格式正确的 `ORCHESTRATOR_WS_URL`，但不会连接该 URL。它恰好采集 20 ms、320 个采样和 640 字节的 L16 负载，然后将一个 RTP 数据包写入标准输出。`frame.rtp` 仅是本地制品。

```bash
BITNP_CAPTURE_DEVICE=default \
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control \
BITNP_MIC_RTP_STREAM_ID=mic-primary \
BITNP_MIC_RTP_TIMESTAMP=0 \
uv run mic-capture > frame.rtp
```
