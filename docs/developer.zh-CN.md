# Mic 开发者文档

Mic 是 Orchestrator-only 的 hub client。它不感知业务策略，也不持有跨服务状态。系统架构、部署编排和规范协议以 [Orchestrator 开发者文档](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/developer.zh-CN.md) 为准；通过 `ORCHESTRATOR_REPO` 引用其 schema。

## 技术栈

Python 3.12+、`uv`、`pytest`、`websockets` 和 `sounddevice`；ASR HTTP 调用仅使用 Python 标准库。命令入口为 `mic-health` 和 `mic-stream`。

## 架构与数据流

`mic-stream` 组合 PortAudio capture、可选 ZipEnhancer ONNX 降噪、Silero VAD ONNX、CAM++、OpenAI-compatible ASR 和 Orchestrator WSS control boundary。20 ms PCM16 块持续采集；Silero VAD 每 32 ms 推理一次并驱动本地端点检测。端点窗口的原始 PCM 只在 Mic 内存中保留到单次模型/ASR 请求完成。

ZipEnhancer 使用阿里语音实验室发布的官方 ONNX 导出格式：输入必须是 `noisy_mag`、`noisy_pha`，输出为 `amp_g`、`pha_g`。Mic 按模型指定的 400-point STFT、100-sample hop、幅度压缩系数 0.3，在 CPU 上处理 16 kHz 单声道 PCM16 的端点窗口；不会安装完整 ModelScope 或 Torch 常驻依赖。由于该 ONNX 是带双侧 STFT 上下文的增强模型，Mic 不会对每一个 20 ms 块单独推理，以免显著增加 CPU 开销和边界伪影。

OpenAI-compatible `/audio/transcriptions` 是一次 multipart 请求，并非流式 ASR 协议。因此采集和本地 VAD 是流式的，而降噪、CAM++ 与该 ASR 请求在端点形成后执行。若设置 `MIC_ASR_ENDPOINT_INCLUDES_VAD=true`，Mic 不加载本地 VAD，并强制每 2 秒提交一个有界窗口，避免无限累积音频；该模式应仅用于服务端确实支持 VAD/分段的 ASR endpoint。

```text
PortAudio input -> 20 ms PCM16 block -> local VAD/endpoint
                                           -> optional ZipEnhancer -> CAM++/ASR
                                           -> WSS voice.evidence/asr.final
                                           -> WSS mic.input.register with Orchestrator
```

## 通信协议

Mic 引用 Orchestrator 的 `schemas/protocol/envelope.schema.json` 和 `schemas/protocol/event-data.schema.json`。输入时钟契约固定为 16 kHz、单声道 PCM16、20 ms（每块 320 samples / 640 bytes）；RTP 范围仅作为结构化事件的时间关联字段，Mic 不发送 RTP。`asr.partial` 仅诊断，只有 `asr.final` 可以进入调度；它必须携带 stream、segment、RTP 起止范围、取消 epoch、文本、接收时间及可选置信度。不要在本仓库复制 schema 或 fixture。

## 模块契约

- 必须只连接 Orchestrator。
- 必须先完成 input register/ready handshake，再发送结构化输入事件。
- 必须保持 20 ms、640-byte PCM16 采集块与连续的时间戳边界。
- 不得向 Orchestrator 发送原始 ASR 音频；只发送有界的结构化结果。不得从 partial 触发业务效果。
- 生产 WSS 必须携带可信局域网 bearer token。
- 生产部署在 `ORCHESTRATOR_TLS_CA_PATH` 设置同一个只读 PEM CA bundle，用于校验 Orchestrator WSS 证书。该路径也由 Orchestrator、Sound、Comments 使用；主机系统信任库只是已安装相同 CA 时的可选替代。

本地安装、测试和健康检查见[用户文档](user.zh-CN.md)。同机 `ws://` 回环联调必须同时设置 `MIC_ALLOW_LOOPBACK_WS=true`、使用 loopback URL，并清空 `TRUSTED_LAN_TOKEN`；集中步骤见[本机回环联调指南](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/local-loopback.zh-CN.md)。真实部署验证应在 Orchestrator 侧确认认证通过、`mic.input.register` 被接受，并且 `asr.final` / `voice.evidence` 只通过同一 control connection 到达。
