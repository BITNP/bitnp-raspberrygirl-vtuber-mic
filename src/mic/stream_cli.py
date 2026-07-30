"""模块契约说明.

职责: 提供 mic.stream_cli
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import asyncio  # noqa: ANYIO_OK - mic-stream requires asyncio UDP transport.

from mic.config import ConfigError
from mic.portaudio_capture import PortAudioBlockCapture
from mic.stream_control import ControlContext, WebSocketStreamingControl
from mic.streaming import (
    AsyncioUdpSender,
    StreamResources,
    StreamRuntime,
    load_streaming_runtime_config,
)


async def run_stream() -> int:
    """函数契约说明.

    功能: 运行流程并协调其依赖步骤。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `int`。
    可能抛出 ConfigError。
    """

    config = load_streaming_runtime_config()

    service_config = config.service_config

    if service_config is None:
        raise ConfigError(
            key="ORCHESTRATOR_WS_URL", reason="must be configured for WSS control"
        )

    control = await WebSocketStreamingControl.open(
        service_config,
        ControlContext(trace_id=config.trace_id, session_id=config.session_id),
    )

    resources = StreamResources(
        capture=PortAudioBlockCapture(device=config.device),
        control=control,
        udp=AsyncioUdpSender(),
    )

    await StreamRuntime(config, resources).run()

    return 0


def main() -> int:
    """函数契约说明.

    功能: 执行命令行或服务入口流程并返回进程级结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `int`。
    """

    return asyncio.run(run_stream())
