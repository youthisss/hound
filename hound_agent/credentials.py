"""Provider credentials stored outside project configuration."""
from __future__ import annotations


SERVICE_NAME = "hound-agent"


def get_api_key(provider_id: str) -> str:
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, f"provider:{provider_id}") or ""
    except Exception:
        return ""


def set_api_key(provider_id: str, api_key: str) -> None:
    import keyring
    keyring.set_password(SERVICE_NAME, f"provider:{provider_id}", api_key)


def delete_api_key(provider_id: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE_NAME, f"provider:{provider_id}")
    except Exception:
        pass
