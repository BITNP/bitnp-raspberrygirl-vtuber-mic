# Mic 开发者文档

Mic 是 Orchestrator-only 的 hub client。它不感知业务策略，也不持有跨服务状态。系统架构、部署编排和规范协议以 [Orchestrator 开发者文档](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/developer.zh-CN.md) 为准；通过 `ORCHESTRATOR_REPO` 引用其 schema。

## 技术栈

Python 3.12+、`uv`、`pytest`、`websockets` 和 `sounddevice`；ASR HTTP 调用仅使用 Python 标准库。命令入口为 `mic-health` 和 `mic-stream`。

## 架构与数据流

`mic-stream` 组合 PortAudio capture、可选 ZipEnhancer ONNX 降噪、Silero VAD ONNX、CAM++、OpenAI-compatible ASR 和 Orchestrator WSS control boundary。20 ms PCM16 块持续采集；ZipEnhancer 在独立的、默认 500 ms 的有界窗口中串行增强，输出的 20 ms 帧才进入 Silero VAD。每个帧只执行一次有状态 Silero 判定，结果同时用于 ASR 端点和 CAM++。CAM++ 按 3D-Speaker 官方 Runtime FBank 契约把增强语音组成 1.5 秒窗口、每 0.75 秒产生一次临时 embedding；端点只结束当前 ASR 段，不能停止采集。

ZipEnhancer 使用阿里语音实验室发布的官方 ONNX 导出格式：输入必须是 `noisy_mag`、`noisy_pha`，输出为 `amp_g`、`pha_g`。Mic 按模型指定的 400-point STFT、100-sample hop、幅度压缩系数 0.3，在 CPU 上完成频谱预处理与重建，并优先使用 CUDA 执行 ONNX 推理，处理 16 kHz 单声道 PCM16 的连续窗口；不会安装完整 ModelScope 或 Torch 常驻依赖。窗口默认为 500 ms 且必须是 20 ms 的整数倍，避免对每一个 20 ms 块单独推理造成 CPU 开销和边界伪影。实时降噪以窗口音频时长为处理时限：超时或失败时原样转发该窗口，迟到增强结果不再使用。最多保留一个在途推理；它尚未结束时后续窗口直接使用原始 PCM，避免计算任务积压。关闭时等待该次推理收尾，防止重连复用模型时遗留工作。此策略保证过载时继续处理音频，不代表慢硬件能持续提供实时降噪。

CAM++ ONNX 只接受官方的 float32 `feature` 输入 `[1, frame_num, 80]` 并输出 `embedding`；不得将 PCM 直接送入模型。Mic 将受控 CAM++、其同名外部权重 `campp.onnx.data`、官方 Runtime `fbank_config.json`、ZipEnhancer 与 Silero VAD ONNX 作为包资源随安装分发，运行时不读取模型路径环境变量。三个处理器分别由默认开启的 `MIC_ENABLE_CAMPP`、`MIC_ENABLE_ZIPENHANCER`、`MIC_ENABLE_SILERO_VAD` 控制；关闭后启动过程不会构造或加载对应 ONNX session。FBank 严格限定 16 kHz、25 ms 窗、10 ms 帧移、80 mel bins、dither 0、power/log FBank 与逐窗均值归一化。CAM++ worker 与 HTTP ASR worker 并行，容量为 2 的 CAM++ 待处理队列在满时淘汰最旧窗口，不等待慢推理或发送完成；每条 evidence 在发送完成后即释放，不记录或持久化 embedding。

OpenAI-compatible `/audio/transcriptions` 是一次 multipart 请求，并非流式 ASR 协议。因此采集和本地 VAD 是流式的，而该 ASR 请求在端点形成后执行。若设置 `MIC_ASR_ENDPOINT_INCLUDES_VAD=true`，Mic 仍加载本地 Silero VAD 供 CAM++ 使用，但按 2 秒有界窗口提交 ASR，避免无限累积音频；该模式应仅用于服务端确实支持 VAD/分段的 ASR endpoint。

```text
PortAudio input -> 20 ms PCM16 block -> optional ZipEnhancer window -> local VAD/endpoint
                                                                       -> CAM++/ASR
                                           -> WSS voice.evidence/asr.final
                                           -> WSS mic.input.register with Orchestrator
```

## 通信协议

Mic 引用 Orchestrator 的 `schemas/protocol/envelope.schema.json` 和 `schemas/protocol/event-data.schema.json`。输入时钟契约固定为 16 kHz、单声道 PCM16、20 ms（每块 320 samples / 640 bytes）；RTP 范围仅作为结构化事件的时间关联字段，Mic 不发送 RTP。`asr.partial` 仅诊断，只有 `asr.final` 可以进入调度；它必须携带 stream、segment、RTP 起止范围、取消 epoch、文本、接收时间及可选置信度。不要在本仓库复制 schema 或 fixture。

## 模块契约

- 必须只连接 Orchestrator。
- 启动时先验证配置并加载所有已启用模型，再打开 control；必须完成 input register/ready handshake 后才打开 PortAudio 并发送结构化输入事件。异常断线会清理 capture、HTTP、WSS 和 worker 后按有抖动的上限 10 秒退避重连。
- 必须保持 20 ms、640-byte PCM16 采集块与连续的时间戳边界。
- 不得向 Orchestrator 发送原始 ASR 音频；只发送有界的结构化结果。不得从 partial 触发业务效果。
- 生产 WSS 必须携带可信局域网 bearer token。
- 生产部署在 `ORCHESTRATOR_TLS_CA_PATH` 设置同一个只读 PEM CA bundle，用于校验 Orchestrator WSS 证书。该路径也由 Orchestrator、Sound、Comments 使用；主机系统信任库只是已安装相同 CA 时的可选替代。

本地安装、测试和健康检查见[用户文档](user.zh-CN.md)。受信任局域网 `ws://` 联调必须设置 `MIC_ALLOW_LOOPBACK_WS=true`，并继续提供 Mic 专属 `TRUSTED_LAN_TOKEN`；集中步骤见[受信任局域网明文联调指南](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/local-loopback.zh-CN.md)。真实部署验证应在 Orchestrator 侧确认认证通过、`mic.input.register` 被接受，并且 `asr.final` / `voice.evidence` 只通过同一 control connection 到达。

关闭 Silero VAD 时，ASR 端点与 CAM++ 共享端点检测器现有的能量判定（平均绝对样本幅度阈值 300），CAM++ 不会随之停用，静音也不会被标为语音。ASR 服务端自带 VAD 时固定窗口的发送策略保持不变。

## 句首缓存与过载恢复

启用本地 Silero 端点检测时保留最多 200 ms 前置音频，弥补 32 ms 判定窗口与检测延迟；语音开始后缓存并入 ASR 端点，时间戳仍指向原始音频范围。服务端 VAD 的固定窗口策略不变。采集断续会清除前置缓存、端点、Silero 状态和 CAM++ 窗口。

ASR 待处理端点与 CAM++ 待处理窗口各保留最多两项；队列满时淘汰最旧的待处理项，正在执行的调用保持原有取消规则。原始帧队列最多 75 帧，过载时同样淘汰旧帧，消费者检测时间戳缺口后重置处理状态，不能跨缺口拼接语音。正常录音结束按队列顺序收尾；连接取消会先停止管线，再关闭采集设备。队列淘汰、断续重置及降噪超时/忙碌回退均记录 DEBUG 诊断。

三个本地模型通过共享 session 工厂优先请求 `CUDAExecutionProvider`，并保留 `CPUExecutionProvider` 执行不支持的算子。CUDA 不可用或初始化失败时回退 CPU；启动 INFO 日志记录每个模型实际启用的 provider，DEBUG 记录请求与实际结果。provider 列表不代表每个算子都在 GPU 上执行。Silero 的状态与窗口、ZipEnhancer 的时限回退和 CAM++ 滑动窗口保持原有语义。

Linux/Windows x86-64 默认安装 `onnxruntime-gpu[cuda,cudnn]`，其余平台安装 CPU 包，避免两个发行包覆盖同一个 Python 模块。GPU 包限制在 1.21–1.23 系列以使用 CUDA 12/cuDNN 9；升级主 CUDA 版本前需重新验证驱动和三个受控模型。通过 `preload_dlls(directory="")` 加载 Python 环境中的 NVIDIA 库，无需 Torch。

GPU 验证记录（RTX 3050，ORT 1.23.2，合成音频）：profiling 确认 ZipEnhancer、Silero、CAM++ 分别有 1688、53、995 次 CUDA 算子事件；CPU 算子仍负责部分形状计算及不支持的运算。这不是纯 GPU 执行。500 ms ZipEnhancer 窗口预热后约 57–66 ms，结果仅代表该机器的短测，不作为持续负载保证。

窄范围运行库警告例外：上述受控 ZipEnhancer 和 CAM++ 图初始化时，ORT 的 `transformer_memcpy.cc` 会报告各插入 2 个 Memcpy 节点。独立 profiling 已确认 CUDA 算子实际执行，详细初始化日志确认这些节点是 CPU/GPU 混合图所需的数据传输；当前未启用 CUDA Graph，因此“不支持 CUDA Graph”的附带提示不影响正确性。保留该条性能提示，不提高全局日志阈值、不屏蔽其他警告；模型、ORT 或执行策略变化后需重新验证。Python 测试和静态检查仍将其他警告视为错误。
