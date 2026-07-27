# Deployment

Set service configuration through the environment shown in `.env.example`; keep credentials outside the repository. Deploy the Mic service beside its RTP route to Orchestrator, then use `uv run mic-health` for its health command. RTP media is 16 kHz on the Mic boundary. Do not configure a direct route to Sound, Comments, or the frontend.
