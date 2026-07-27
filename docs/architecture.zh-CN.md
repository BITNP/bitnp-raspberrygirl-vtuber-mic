# 架构

Mic 采集或回放音频，再将 16 kHz RTP 媒体和规范控制事件发送给 Orchestrator。Orchestrator 拥有 ASR 与所有跨服务决策。Mic 不感知模式，因此 `lecturer`、`virtual_streamer` 和 `onsite_explainer` 不会改变其契约。
