# 架构

Mic 是只连接 Orchestrator 的中心客户端。`mic-stream` 打开经认证的 WSS 控制连接，绑定配置的本地 UDP 套接字，注册音源路由，等待 `media.rtp.source.ready`，然后只向配置的 Orchestrator UDP RTP 接入端点发送 RTP。它没有对等服务地址或连接。Orchestrator 拥有 ASR 和跨服务决策。

媒体契约是每个完整的 16 kHz 单声道采集块对应一个固定的 RTP V2/PT96/L16 数据包，包含 320 个采样、20 ms 时长和 640 字节负载。Mic 不感知业务策略，因此产品场景和 Orchestrator 交互选择不会改变其契约。
