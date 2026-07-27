# 部署

通过 `.env.example` 所示的环境变量配置服务，凭据不得进入仓库。将 Mic 服务部署在连接 Orchestrator 的 RTP 路径旁，并用 `uv run mic-health` 执行健康检查。Mic 边界上的 RTP 媒体为 16 kHz。不得直接连接 Sound、Comments 或前端。
