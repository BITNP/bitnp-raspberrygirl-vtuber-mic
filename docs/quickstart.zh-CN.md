# 快速开始

使用 Python 3.12 或更高版本。在本仓库中运行：

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run mic-health
```

默认路径使用本地 mock 或回放输入。服务向 Orchestrator 输出 16 kHz RTP 音频。测试不需要麦克风设备、GPU 或凭据。
