"""
Shared Telethon client singleton.

Both father_gateway and the Tessia Bot brain share the same Telethon
client through this module. The father gateway starts the client and
registers it here; the Tessia Bot reads it when it needs to execute
tools on the father's account.

Usage:
    from tessia_bot.telethon_client_manager import set_client, get_client

    # In father_gateway:
    client = TelegramClient(...)
    await client.start()
    set_client(client)

    # In tessia bot (when tool is needed):
    client = get_client()
    if client and client.is_connected():
        result = await tool_fn(client, ...)
"""

from __future__ import annotations

from telethon import TelegramClient

_telethon_client: TelegramClient | None = None
_telethon_client_ready: bool = False


def set_client(client: TelegramClient) -> None:
    """Register the active Telethon client for shared use."""
    global _telethon_client, _telethon_client_ready
    _telethon_client = client
    _telethon_client_ready = True


def get_client() -> TelegramClient | None:
    """Get the shared Telethon client, or None if not started yet."""
    return _telethon_client


def is_ready() -> bool:
    """Check if the Telethon client has been registered and is connected."""
    global _telethon_client_ready, _telethon_client
    if not _telethon_client_ready or _telethon_client is None:
        return False
    try:
        return _telethon_client.is_connected()
    except Exception:
        return False


def clear_client() -> None:
    """Clear the client reference (e.g. on disconnect)."""
    global _telethon_client, _telethon_client_ready
    _telethon_client = None
    _telethon_client_ready = False
