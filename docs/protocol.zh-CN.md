# 协议子集

Mic 是中心客户端，不是对等服务。请将 `ORCHESTRATOR_REPO` 设置为 Orchestrator 检出目录，并读取其中的规范契约：`$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` 和 `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`。Mic 只参与自身的控制与 RTP 媒体子集，不复制 schema 或 fixture。
