# Quickstart

Use Python 3.12 or later. From this repository, run:

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run mic-health
```

The normal path is local mock or replay input. The service produces 16 kHz RTP audio for the Orchestrator. It does not require a microphone device, GPU, or credentials for tests.
