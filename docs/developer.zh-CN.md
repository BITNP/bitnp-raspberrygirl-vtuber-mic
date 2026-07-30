# Mic 开发者文档

Mic 是 Orchestrator-only 的 hub client。它不感知 `lecturer`、`virtual_streamer` 或 `onsite_explainer`，也不持有跨服务状态。

## 技术栈

Python 3.12+、`uv`、`pytest`、`websockets` 和 `sounddevice`。命令入口为 `mic-health`、`mic-capture` 和 `mic-stream`。

## 架构与数据流

`mic-stream` 组合 PortAudio capture、Orchestrator WSS control boundary 和 UDP RTP sender。启动后先绑定本地 UDP，再通过 WSS 发送 `media.rtp.source.register`。只有收到匹配的 `media.rtp.source.ready` 后，捕获帧才会被转为 RTP 并发往 Orchestrator。

```text
PortAudio input -> 20 ms PCM16 block -> L16 RTP packet -> Orchestrator UDP ingress
                                 \-> WSS register/ready with Orchestrator
```

## 通信协议

Mic 引用 Orchestrator 的 `schemas/protocol/envelope.schema.json` 和 `schemas/protocol/event-data.schema.json`。媒体契约固定为 L16、16 kHz、mono、payload type 96、每帧 320 samples。不要在本仓库复制 schema 或 fixture。

## 模块契约

- 必须只连接 Orchestrator。
- 必须先完成 source register/ready handshake，再发送媒体。
- 必须保持 20 ms、640-byte L16 payload 的 RTP 封包边界。
- 生产 WSS 必须携带可信局域网 bearer token。
- `mic-capture` 是本地诊断，不建立部署媒体链路。

## 验证

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health
```

真实部署验证应在 Orchestrator 侧确认认证通过、`media.rtp.source.register` 被接受、ready 先于媒体到达，并且 UDP RTP 抵达配置的 ingress。
