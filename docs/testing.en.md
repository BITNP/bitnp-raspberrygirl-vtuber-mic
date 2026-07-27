# Testing

Run `uv sync --locked` once, then run `uv run pytest`. The suite covers the replay path and RTP behavior without live audio hardware. Run `ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run mic-health` as a small command surface check.
