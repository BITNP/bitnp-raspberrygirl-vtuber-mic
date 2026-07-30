"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from mic.capture import load_capture_runtime_config, run_capture
from mic.portaudio_capture import CaptureDevice, RawInputStream


@dataclass(slots=True)
class FakeRawInputStream:
    """类契约说明.

    职责: 保存 FakeRawInputStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: data、read_sizes、exited。 方法:
    __enter__、__exit__、read。
    """

    data: bytes

    read_sizes: list[int] = field(default_factory=list)

    exited: bool = False

    def __enter__(self) -> Self:
        """函数契约说明.

        功能: 执行 __enter__ 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `Self`。
        """

        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """函数契约说明.

        功能: 执行 __exit__ 的同步逻辑,并产出
        exited。
        参数: self 表示当前实例。 exception_type:
        type[BaseException] | None。 必填。
        exception: BaseException | None。
        必填。 traceback: TracebackType |
        None。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.exited = True

    def read(self, frames: int) -> tuple[bytes, bool]:
        """函数契约说明.

        功能: 执行 read 的同步逻辑,并协调 append。
        参数: self 表示当前实例。 frames: int。
        必填。
        契约: 同步调用。 返回 `tuple[bytes,
        bool]`。
        """

        self.read_sizes.append(frames)

        return self.data, False


@dataclass(slots=True)
class FakeRawInputStreamFactory:
    """类契约说明.

    职责: 保存 FakeRawInputStreamFactory
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream、devices。 方法:
    __call__。
    """

    stream: RawInputStream

    devices: list[CaptureDevice] = field(default_factory=list)

    def __call__(self, device: CaptureDevice) -> RawInputStream:
        """函数契约说明.

        功能: 执行 __call__ 的同步逻辑,并协调
        append。
        参数: self 表示当前实例。 device:
        CaptureDevice。 必填。
        契约: 同步调用。 返回 `RawInputStream`。
        """

        self.devices.append(device)

        return self.stream


@dataclass(slots=True)
class FakeStdout:
    """类契约说明.

    职责: 保存 FakeStdout
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: writes。 方法: write、flush。
    """

    writes: list[bytes] = field(default_factory=list)

    def write(self, packet: bytes) -> int:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并协调 append,
        len。
        参数: self 表示当前实例。 packet: bytes。
        必填。
        契约: 同步调用。 返回 `int`。
        """

        self.writes.append(packet)

        return len(packet)

    def flush(self) -> None:
        """函数契约说明.

        功能: 执行 flush 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        return


def test_run_capture_packetizes_one_configured_portaudio_frame_to_stdout_without_hardware() -> (
    None
):
    # Given: explicit capture and stream settings plus an injected RawInputStream.

    """函数契约说明.

    功能: 验证 run capture packetizes one
    configured portaudio frame to stdout
    without hardware 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    payload = bytes(range(256)) * 2 + bytes(range(128))

    stream = FakeRawInputStream(data=payload)

    factory = FakeRawInputStreamFactory(stream=stream)

    output = FakeStdout()

    env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_CAPTURE_DEVICE": "12",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: the production capture composition runs through the existing boundary.

    exit_code = run_capture(env, factory, output)

    # Then: it writes exactly one packetized L16 frame to stdout and closes the stream.

    assert exit_code == 0

    assert len(output.writes) == 1

    assert len(output.writes[0]) == 12 + 640

    assert output.writes[0][4:8] == (96000).to_bytes(4, byteorder="big")

    assert output.writes[0][12:] == b"".join(
        payload[index : index + 2][::-1] for index in range(0, len(payload), 2)
    )

    assert factory.devices == [12]

    assert stream.read_sizes == [320]

    assert stream.exited is True


def test_load_capture_runtime_config_uses_default_or_name_capture_device() -> None:
    # Given: required RTP settings and either omitted or named neutral capture device selection.

    """函数契约说明.

    功能: 验证 load capture runtime config
    uses default or name capture device
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    required_env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: runtime configuration is parsed from each selection form.

    default_config = load_capture_runtime_config(required_env)

    named_config = load_capture_runtime_config(
        {**required_env, "BITNP_CAPTURE_DEVICE": "USB Microphone"}
    )

    # Then: omission uses the host default while a query remains a name.

    assert default_config.device is None

    assert named_config.device == "USB Microphone"


def test_load_capture_runtime_config_uses_portaudio_default_for_default_device_literal() -> (
    None
):
    # Given: required RTP settings and the documented default device literal.

    """函数契约说明.

    功能: 验证 load capture runtime config
    uses portaudio default for default
    device literal 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    env = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "BITNP_CAPTURE_DEVICE": "default",
        "BITNP_MIC_RTP_STREAM_ID": "mic-cli",
        "BITNP_MIC_RTP_TIMESTAMP": "96000",
    }

    # When: runtime configuration parses the literal.

    config = load_capture_runtime_config(env)

    # Then: it uses PortAudio's None default-device selector.

    assert config.device is None
