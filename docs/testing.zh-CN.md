# 测试

先运行一次 `uv sync --locked`，再运行 `uv run pytest`。测试覆盖回放路径和 RTP 行为，无需真实音频硬件。可运行 `ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run mic-health` 检查命令行入口。
