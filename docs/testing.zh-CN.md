# 测试

先运行一次 `uv sync --locked`，再运行 `uv run pytest`。测试覆盖回放、RTP 封包、流配置、WSS 安全策略和运行时顺序，无需真实音频硬件。可运行 `ORCHESTRATOR_WS_URL=wss://orchestrator.example.test/control uv run mic-health` 检查本地命令行入口。它只验证配置解析，不验证 Orchestrator 可达性。

进行真实部署检查时，应为 `mic-stream` 配置生产 WSS URL、可信局域网 Bearer token 和 Orchestrator UDP RTP 接入端点。运行 `uv run mic-stream`，然后在 Orchestrator 侧确认 Bearer 认证成功、`media.rtp.source.register` 被接受、匹配的 `media.rtp.source.ready` 在媒体之前到达，并且 UDP RTP 帧到达配置的接入端点。使用正整数的 `MIC_MAX_CAPTURE_BLOCKS` 进行有限次数的运行。除明确的回环测试外，必须使用 WSS。

实时采集需要可用的 PortAudio 输入和操作系统授予的录音权限。不设置 `BITNP_CAPTURE_DEVICE` 或将其设为 `default` 时使用主机默认输入，也可使用可用设备的索引或名称查询。
