"""模块契约说明.

职责: 提供 mic.security
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from mic.config import ServiceConfig


def trusted_lan_auth_header(config: ServiceConfig) -> dict[str, str]:
    """函数契约说明.

    功能: 执行 trusted_lan_auth_header
    的同步逻辑,并维持签名契约。
    参数: config: ServiceConfig。 必填。
    契约: 同步调用。 返回 `dict[str, str]`。
    """

    if config.trusted_lan_token is None:
        return {}

    return {"authorization": f"Bearer {config.trusted_lan_token}"}


def trusted_lan_token_is_valid(
    config: ServiceConfig, authorization: str | None
) -> bool:
    """函数契约说明.

    功能: 执行 trusted_lan_token_is_valid
    的同步逻辑,并维持签名契约。
    参数: config: ServiceConfig。 必填。
    authorization: str | None。 必填。
    契约: 同步调用。 返回 `bool`。
    """

    if config.trusted_lan_token is None:
        return True

    return authorization == f"Bearer {config.trusted_lan_token}"
