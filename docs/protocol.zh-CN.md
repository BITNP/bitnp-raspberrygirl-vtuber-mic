# 协议子集

Mic 是中心客户端，而不是对等服务。请将 `ORCHESTRATOR_REPO` 设置为 Orchestrator 检出目录，并读取其中的规范契约：`$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` 和 `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`。Mic 不复制 schema 或 fixture。

`mic-stream` 只连接 Orchestrator。它通过经认证的 WSS 发送 `media.rtp.source.register`，其中包含流 ID、固定的 Mic SSRC、L16 编解码信息和配置的 Orchestrator RTP 接入端点。必须先收到匹配的 `media.rtp.source.ready` 事件，才能发送 UDP 媒体。每个 RTP 数据包均为 V2/PT96/L16，使用 16 kHz 单声道，每帧 320 个采样。生产控制连接必须使用 WSS 和 `TRUSTED_LAN_TOKEN`，明文 `ws://` 只限于设置 `MIC_ALLOW_LOOPBACK_WS=true` 的明确回环测试。
