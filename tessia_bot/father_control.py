import json
import os

from .config import FATHER_AUTO_REPLY_ENABLED, FATHER_GATEWAY_STATE_FILE, FATHER_PERSONA_FILE, FATHER_WHITELIST_FILE


def default_whitelist_state():
    return {"enabled": True, "allowed_user_ids": [], "allowed_usernames": []}


def load_father_whitelist():
    if not os.path.exists(FATHER_WHITELIST_FILE):
        return default_whitelist_state()
    with open(FATHER_WHITELIST_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    data = default_whitelist_state()
    data["enabled"] = bool(raw.get("enabled", True))
    data["allowed_user_ids"] = [str(item) for item in raw.get("allowed_user_ids", []) if str(item).strip()]
    data["allowed_usernames"] = [str(item).lower().lstrip("@") for item in raw.get("allowed_usernames", []) if str(item).strip()]
    return data


def save_father_whitelist(data: dict):
    normalized = default_whitelist_state()
    normalized["enabled"] = bool(data.get("enabled", True))
    normalized["allowed_user_ids"] = [str(item) for item in data.get("allowed_user_ids", []) if str(item).strip()]
    normalized["allowed_usernames"] = [str(item).lower().lstrip("@") for item in data.get("allowed_usernames", []) if str(item).strip()]
    with open(FATHER_WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)


def is_sender_allowed(sender_id: str, username: str, whitelist: dict) -> bool:
    if not whitelist.get("enabled", True):
        return False
    allowed_ids = set(whitelist.get("allowed_user_ids", []))
    allowed_usernames = set(whitelist.get("allowed_usernames", []))
    normalized_username = (username or "").lower().lstrip("@")
    return sender_id in allowed_ids or (normalized_username and normalized_username in allowed_usernames)


def add_whitelist_entry(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    data = load_father_whitelist()
    if value.startswith("@"):
        value = value[1:]
    if value.isdigit():
        if value not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(value)
            save_father_whitelist(data)
        return True
    normalized = value.lower()
    if normalized not in data["allowed_usernames"]:
        data["allowed_usernames"].append(normalized)
        save_father_whitelist(data)
    return True


def remove_whitelist_entry(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    data = load_father_whitelist()
    changed = False
    if value.startswith("@"):
        value = value[1:]
    if value.isdigit() and value in data["allowed_user_ids"]:
        data["allowed_user_ids"] = [item for item in data["allowed_user_ids"] if item != value]
        changed = True
    normalized = value.lower()
    if normalized in data["allowed_usernames"]:
        data["allowed_usernames"] = [item for item in data["allowed_usernames"] if item != normalized]
        changed = True
    if changed:
        save_father_whitelist(data)
    return changed


def set_whitelist_enabled(enabled: bool):
    data = load_father_whitelist()
    data["enabled"] = bool(enabled)
    save_father_whitelist(data)


def get_father_runtime_status() -> dict:
    whitelist = load_father_whitelist()
    persona = load_father_persona()
    gateway_state = load_gateway_runtime_state()
    return {
        "gateway_env_enabled": FATHER_AUTO_REPLY_ENABLED,
        "gateway_runtime_enabled": gateway_state.get("enabled", True),
        "whitelist_enabled": whitelist.get("enabled", True),
        "allowed_user_ids_count": len(whitelist.get("allowed_user_ids", [])),
        "allowed_usernames_count": len(whitelist.get("allowed_usernames", [])),
        "persona_entries_count": len(persona),
    }


def load_father_persona():
    if not os.path.exists(FATHER_PERSONA_FILE):
        return {}
    with open(FATHER_PERSONA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_father_persona(data: dict):
    with open(FATHER_PERSONA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_persona_note(target: str, note: str):
    target = (target or "").strip().lower().lstrip("@")
    note = (note or "").strip()
    if not target:
        return False
    data = load_father_persona()
    if note:
        data[target] = note
    else:
        data.pop(target, None)
    save_father_persona(data)
    return True


def get_persona_note(target: str) -> str:
    target = (target or "").strip().lower().lstrip("@")
    if not target:
        return ""
    data = load_father_persona()
    return str(data.get(target, "")).strip()


def load_gateway_runtime_state():
    if not os.path.exists(FATHER_GATEWAY_STATE_FILE):
        return {"enabled": True}
    with open(FATHER_GATEWAY_STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"enabled": bool(data.get("enabled", True))}


def set_gateway_runtime_enabled(enabled: bool):
    with open(FATHER_GATEWAY_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": bool(enabled)}, f, ensure_ascii=False, indent=2)


def is_gateway_runtime_enabled() -> bool:
    return bool(load_gateway_runtime_state().get("enabled", True))
