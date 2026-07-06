# TessiaAiBot — Telethon Tools & AI Tool Execution Layer

> **Plan for implementing a complete Telethon tool layer, a runtime executor, and an OpenAI function-calling brain for the Father Gateway.**

**Goal:** Replace the current hardcoded `father_gateway.py` auto-reply with a full tool-based architecture where an AI (OpenAI/OpenRouter) receives Telegram events, decides which Telethon tool to call, and executes it — exactly like an agent using tools.

**Architecture:**
```
Telegram Event (from Telethon listener)
    ↓
IncomingMessagePayload (brain_api.py)
    ↓
OpenAI function-calling brain → decides tool + params
    ↓
Tool Executor → calls the right Telethon tool function
    ↓
Telethon API → action done
```

**Tech Stack:** Python 3.11, Telethon, OpenAI SDK, Pydantic

---

## Phase 1: Telethon Tool Functions (`telethon_tools.py`)

Create a single file `tessia_bot/telethon_tools.py` with 20+ async functions that wrap Telethon API calls. Each tool has:
- Clear typed signature (Pydantic-validated inputs)
- Error handling
- Logging
- OpenAI function-call schema (as JSON docstring or separate dict)

### Task 1.1: Create `telethon_tools.py` — Send/Edit/Delete tools

**Objective:** Implement core message tools: send_message, reply_message, forward_messages, edit_message, delete_messages

**Files:**
- Create: `tessia_bot/telethon_tools.py`
- Modify: none yet

**Functions to implement:**
```python
async def send_message(client, chat_id, text, parse_mode="markdown"):
async def reply_message(client, event, text, parse_mode="markdown"):
async def forward_messages(client, to_chat, from_chat, message_ids):
async def edit_message(client, chat_id, message_id, new_text):
async def delete_messages(client, chat_id, message_ids):
```

### Task 1.2: Add Media/File tools

**Functions:**
```python
async def send_file(client, chat_id, file_path, caption=""):
async def send_photo(client, chat_id, photo_path, caption=""):
async def send_voice(client, chat_id, voice_path, caption=""):
async def send_media_group(client, chat_id, media_list):
async def download_media(client, message, output_dir="downloads"):
```

### Task 1.3: Add Group/Channel management tools

**Functions:**
```python
async def get_participants(client, chat_id):
async def kick_participant(client, chat_id, user_id):
async def ban_participant(client, chat_id, user_id):
async def unban_participant(client, chat_id, user_id):
async def add_participant(client, chat_id, user_id):
async def leave_chat(client, chat_id):
async def create_group(client, title, users):
async def create_channel(client, title, about=""):
```

### Task 1.4: Add Query/Info tools

**Functions:**
```python
async def get_dialogs(client, limit=100):
async def get_entity(client, identifier):
async def get_messages(client, chat_id, limit=50):
async def get_message_by_id(client, chat_id, message_id):
async def search_messages(client, chat_id, query, limit=20):
async def get_user_info(client, user_id):
```

### Task 1.5: Add Admin/Utility tools

**Functions:**
```python
async def pin_message(client, chat_id, message_id):
async def unpin_message(client, chat_id):
async def mark_read(client, chat_id):
async def set_profile_photo(client, photo_path):
async def update_profile(client, first_name="", last_name="", bio=""):
async def export_chat_invite_link(client, chat_id):
```

### Task 1.6: Define OpenAI Function-Calling Schemas

In the same file, define a dict `TOOL_SCHEMAS` that maps each tool name to its OpenAI function-call JSON schema:

```python
TOOL_SCHEMAS = {
    "send_message": {
        "name": "send_message",
        "description": "Send a text message to a Telegram chat/user",
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "Chat ID, username, or phone number"},
                "text": {"type": "string", "description": "Message text"},
                "parse_mode": {"type": "string", "enum": ["markdown", "html", None]}
            },
            "required": ["chat_id", "text"]
        }
    },
    # ... each tool
}
```

Also define a `TOOL_MAP` dict:
```python
TOOL_MAP = {
    "send_message": send_message,
    "forward_messages": forward_messages,
    # ...
}
```

---

## Phase 2: Upgrade Automation Layer (`automation.py`)

### Task 2.1: Extend `AutomationAction` with tool routing

**Objective:** Connect the action model to real Telethon tool names.

**Files:**
- Modify: `tessia_bot/automation.py`

Add a mapping from `AutomationAction.action` values to Telethon tool names:

```python
ACTION_TO_TOOL = {
    "ignore": None,
    "reply_text": "reply_message",
    "reply_voice": "send_voice",
    "request_file": "send_message",  # with a request prompt
    "forward_to_group": "forward_messages",
    "mention_user": "send_message",
    "wait_for_file": "send_message",
    "mark_for_review": "forward_messages",
}
```

### Task 2.2: Add Action-to-Tool Executor Helper

```python
async def execute_action(client, action: AutomationAction, event_context: dict) -> dict:
    """Route an AutomationAction to the correct Telethon tool and execute it."""
```

---

## Phase 3: Upgrade `father_gateway.py` — The Brain Runtime

### Task 3.1: Rewrite `father_gateway.py` to use OpenAI function-calling

**Objective:** Instead of hardcoded system prompt + reply, use OpenAI with tool definitions so the AI decides which tool to call and with what params.

**Files:**
- Rewrite: `father_gateway.py`

**New flow (simplified):**
```
1. Receive Telethon event
2. Check whitelist, rate limit, runtime status
3. Build message:
   - System prompt (existing FATHER_DM_SYSTEM_PROMPT)
   - Conversation history (50 messages)
   - Current user message
4. Call OpenAI with tools=TOOL_SCHEMAS
5. If AI returns tool_call → call TOOL_MAP[tool_name](**args) via executor
6. If AI returns text → use reply_message tool
7. Send result back
```

**Step 1: Build the OpenAI message call**

```python
async def brain_decide_action(client, user_id, messages_history, tools):
    response = await openai_client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages_history,
        tools=tools,  # <-- the TOOL_SCHEMAS list
        tool_choice="auto",
        temperature=0.5,
        max_tokens=500,
    )
    return response.choices[0].message
```

**Step 2: Handle tool calls**

```python
async def handle_tool_call(client, tool_call, event_context):
    tool_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
    tool_func = TOOL_MAP.get(tool_name)
    if tool_func:
        result = await tool_func(client, **arguments)
        return result
```

**Step 3: Multiple rounds (if AI chains tools)**

Allow the AI to call multiple tools in sequence:

```python
while True:
    message = await brain_decide_action(...)
    if message.tool_calls:
        for tool_call in message.tool_calls:
            await handle_tool_call(...)
        # Optionally send results back to AI for follow-up
    else:
        # Final text response
        await reply_message(client, event, message.content)
        break
```

---

## Phase 4: Stateful Multi-Step Automation Runtime (Future)

### Task 4.1: Create `automation_runtime.py`

**Objective:** Support workflows like "ask user for file → inspect → forward to group → notify father". This is the stateful multi-step execution mentioned in `automation_README.md`.

**Files:**
- Create: `tessia_bot/automation_runtime.py`

This file will:
- Track pending workflows per user/conversation
- Handle `wait_for_file` actions (pause and resume on next message)
- Manage review queue (`mark_for_review` → hold messages for father approval)

---

## Phase 5: Integration & Cleanup

### Task 5.1: Update `main.py`

Ensure both services (`tessia_bot` aiogram and `father_gateway` Telethon) still start correctly with the new architecture.

### Task 5.2: Update `requirements.txt`

No changes needed — Telethon, OpenAI, and Pydantic are already there.

### Task 5.3: Add `father_tools_README.md`

A brief doc explaining the tool architecture:
- How tools are defined
- How the AI chooses tools
- How to add a new tool (2 steps: write function + add schema)

### Task 5.4: Commit & Push

```bash
git add .
git commit -m "feat: add Telethon tools layer + AI function-calling brain"
git push origin main
```

---

## Summary of Files Changed

| File | Action | Lines (est.) |
|------|--------|-------------|
| `tessia_bot/telethon_tools.py` | **Create** | ~550 (20+ tools + schemas + TOOL_MAP) |
| `tessia_bot/automation.py` | **Modify** | ~+30 (ACTION_TO_TOOL map, execute_action) |
| `father_gateway.py` | **Rewrite** | ~200 (OpenAI tool-calling brain) |
| `tessia_bot/automation_runtime.py` | **Create** (Phase 4) | ~200 (stateful workflows) |
| `father_tools_README.md` | **Create** (optional) | ~50 |

## Validation

After each phase:
1. `python -c "from tessia_bot.telethon_tools import *; print('OK')"` — verifies imports
2. `python -c "from tessia_bot.automation import execute_action; print('OK')"` — verifies action executor
3. Full dry-run: `python main.py` — let it start, check logs, send a test event
4. Expected: AI receives event → decides tool → executes → response sent

## Risks & Open Questions

- **API key exposure:** `config.py` has hardcoded keys — should move to env vars
- **Tool call loops:** Need a max_tool_calls limit (e.g., 5) to prevent infinite loops
- **Error recovery:** If a tool call fails, should AI retry or give up? Decision: give up & log
- **2FA on Telethon:** First-run still needs phone login — document this
- **Tool choice vs forcing:** For now `tool_choice="auto"` — AI decides. Can add specific tool forcing later
