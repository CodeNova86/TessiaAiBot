# TessiaAiBot — Codebase Problem Analysis

After reading all key files, here are the **11 issues** found:

---

## 🔴 Critical Issues

### 1. Whitelist Checked Twice, Blocks Father Self-Commands
**File:** `father_gateway.py` lines 355-398

The whitelist is checked in TWO places:
- Line 361-364: `if not is_self_command: ... whitelist check` ✅
- Line 391-398: `if not is_self_command and not is_sender_allowed(...)` ❌

**Problem:** The second check (line 392) runs for **self-commands too** (`is_self_command=False` actually means it runs for incoming only). But wait — for self-commands, `is_self_command=True`, so line 392 passes. But `sender_id` (line 372) is the father's own ID for self-commands. If his ID isn't in the whitelist, `is_sender_allowed` returns False and the command is blocked! This means `تسیا` commands to other people's DMs **can randomly fail**.

**Fix:** Remove one of the duplicate checks. Move whitelist logic to one place.

### 2. Three `event.get_sender()` Calls
**File:** `father_gateway.py` lines 356, 368, 372

For non-self-commands:
- Line 356: `await event.get_sender()` — for whitelist check
- Line 368: `await event.get_sender()` — again
- Line 372: `sender.id` — from the second call

**Problem:** Extra API call to Telegram. Redundant.

### 3. API Key Exposed in Source
**File:** `config.py` line 6

```python
TEXT_API_KEY = "sk-afc2375580623837-kmaznl-cee6358f"
```

**Problem:** Hardcoded API key committed to git. Anyone with repo access can use it.

### 4. Father Facts Seeded Twice
**File:** `config.py` lines 27-41 AND `father_gateway.py` lines 487-496

```python
# In config.py:
ensure_facts_seeded()  # Seeds on import

# In father_gateway.py:
fact_memory.add_fact(...)  # Seeds AGAIN on start
```

**Problem:** Facts are added twice with `confidence=1.0` each time. Wasteful but not breaking.

---

## 🟡 Moderate Issues

### 5. Telethon Block Prevents Legitimate Group Actions
**File:** `telethon_tools.py` lines 1694-1711

```python
sending_tools = {
    ..., "ban_participant", "kick_participant", ...
}
if tool_name in sending_tools:
    return {"success": False, "error": "Cannot use ..."}
```

**Problem:** When the user says "تسیا بن کن فلانی رو" in a group, the AI calls `ban_participant` and gets blocked. The user explicitly WANTS this to work in groups via the father's Telethon account.

**Fix:** Only block `send_message/send_file/send_photo` in groups. Allow `ban_participant`, `kick_participant`, etc.

### 6. One Crash Kills Both Services
**File:** `main.py` line 27

```python
await asyncio.gather(
    run_service("tessia_bot", tessia_bot_main),
    run_service("father_gateway", father_gateway_main),
)
```

**Problem:** `gather` with default `return_exceptions=False` means if ONE service crashes, the OTHER gets cancelled too. The father gateway crashing takes down Tessia Bot and vice versa.

### 7. `brain_loop` Unused Tool Result Loop
**File:** `father_gateway.py` lines 252-259

After executing ALL tool calls, if `tool_calls_remaining > 0`, the code goes back to the while loop. But if `tool_calls_remaining <= 0`, it does ONE final LLM call and returns. 

**Problem:** If there are 5 tool calls and the AI calls 5 tools, `tool_calls_remaining` goes 4→3→2→1→0. At 0, it returns after the last tool call result without giving the AI a chance to formulate a final response to the user.

---

## 🟢 Minor Issues

### 8. `run_python_code` Without Code Still Consumes a Round
**File:** `father_gateway.py` lines 210-219

If `run_python_code` is called without `code`, it `continue`s but still decremented `tool_calls_remaining`. The AI wastes a round.

### 9. SYSTEM_PROMPT Missing Explicit Father Rule for Normal Chat Path
**File:** `bot.py` lines 888-905

The SYSTEM_PROMPT doesn't mention the father's user ID. It relies entirely on `build_common_system_context` which injects facts. But for the normal chat path, without facts loaded, the AI might not know the user is the father.

### 10. `event.message.delete()` Can Fail for Outgoing Messages in DM
**File:** `father_gateway.py` line 439

When the father sends `تسیا ...` in someone else's DM, the code tries to `event.message.delete()`. But Telethon's `Message.delete()` for outgoing messages in a DM with another person may fail if the message is too old or already deleted.

### 11. `should_answer()` Only Checks Text, Not Captions
**File:** `bot.py` lines 1497-1507

```python
if message.text and (message.text.lower().startswith("تسیا") or ...):
    return True
if message.caption and (message.caption.lower().startswith("تسیا") or ...):
    return True
```

**Problem:** Only checks `text` and `caption` separately. A message with BOTH text and a photo with caption starting with "تسیا" works, but the `hasattr` checks in `build_recent_chat_messages` in the gateway might still crash on `msg.document.file_name` for certain document types.

---

## Summary

| Priority | Count | Key Fixes |
|----------|-------|-----------|
| 🔴 Critical | 4 | Remove duplicate whitelist + get_sender, hide API key, dedupe seeding |
| 🟡 Moderate | 3 | Allow kick/ban in groups, isolated error handling, fix tool loop |
| 🟢 Minor | 4 | Clean up edge cases, add father rule to prompt |
