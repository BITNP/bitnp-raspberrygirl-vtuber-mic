# 部署

使用 `.env.example` 作为 `mic-stream` 的变量参考。Mic 只连接 Orchestrator。将 `ORCHESTRATOR_WS_URL` 设为已部署的 Orchestrator WSS 控制端点，并从部署密钥存储中加载 `TRUSTED_LAN_TOKEN`。不要将 Bearer token 写入仓库。生产环境必须使用 WSS 和 token。Mic 不生成或管理 TLS 证书。只有当 `MIC_ALLOW_LOOPBACK_WS=true` 且 URL 主机为 `127.0.0.1`、`::1` 或 `localhost` 时，才接受明文 `ws://`，并且只能用于明确的回环测试。

将 `ORCHESTRATOR_RTP_HOST` 和 `ORCHESTRATOR_RTP_PORT` 设为由 Orchestrator 拥有的 UDP RTP 接入端点。`MIC_RTP_BIND_HOST` 和 `MIC_RTP_BIND_PORT` 选择 Mic 的本地 UDP 绑定，端口 `0` 会选择临时端口。每个流都必须设置 `BITNP_MIC_RTP_STREAM_ID`、`BITNP_MIC_RTP_TIMESTAMP`、`BITNP_TRACE_ID` 和 `BITNP_SESSION_ID`。`BITNP_MIC_RTP_TIMESTAMP` 必须是无符号 32 位整数。现场链路中，`BITNP_SESSION_ID` 和 `BITNP_MIC_RTP_STREAM_ID` 必须与 Sound 的 `SOUND_SESSION_ID` 和 `SOUND_RTP_STREAM_ID` 完全一致。不设置 `MIC_MAX_CAPTURE_BLOCKS` 时会持续采集，设置为正整数时用于有限次数的验证运行。

实时采集使用 `sounddevice` 和 PortAudio。部署前运行 `uv sync --locked`。在 Windows 和 macOS 上，允许运行 `mic-stream` 的进程访问麦克风。在 Linux 上，安装发行版提供的 PortAudio 运行时，并授予服务账户录音权限。不设置 `BITNP_CAPTURE_DEVICE` 或将其设为 `default` 时使用主机默认输入，也可使用可用设备的索引或名称查询。

使用 `uv run mic-stream` 启动运行时。它先绑定 UDP，再发送经认证的 `media.rtp.source.register` 控制事件，等待匹配的 `media.rtp.source.ready` 事件，然后为每个完整的 16 kHz 单声道采集块向 Orchestrator 发送一个 V2/PT96/L16 RTP 数据包。每个数据包包含 320 个采样，即 20 ms 的 L16 音频。验证真实部署时，应在 Orchestrator 侧确认 WSS Bearer 认证成功，已注册的流和 SSRC 收到 `media.rtp.source.ready`，并且配置的 UDP 接入端点收到 RTP 帧。Mic 没有现场模式设置，也绝不直接连接 Sound。`mic-capture` 只是本地标准输出诊断工具。
