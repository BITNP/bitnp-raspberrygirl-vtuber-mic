
from mic.config import ServiceConfig


def trusted_lan_auth_header(config: ServiceConfig) -> dict[str, str]:

    if config.trusted_lan_token is None:
        return {}

    return {"authorization": f"Bearer {config.trusted_lan_token}"}


def trusted_lan_token_is_valid(
    config: ServiceConfig, authorization: str | None
) -> bool:

    if config.trusted_lan_token is None:
        return True

    return authorization == f"Bearer {config.trusted_lan_token}"
