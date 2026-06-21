Automation architecture notes

This project now has a dedicated automation layer intended for future father-account workflows.

Goals:
- Keep Telegram user-account transport separate from AI decision logic.
- Use a narrow JSON contract between gateway and brain.
- Keep actions enum-based and policy-controlled.
- Support future multi-step workflows such as:
  - wait for a message from a specific user
  - ask for a file
  - inspect file contents
  - forward to a group
  - mention a specific person

Current modules:
- `automation.py`: rule model, event model, action model, and rule matching
- `brain_api.py`: request/response schema for future gateway -> brain communication
- `tessia_automation_rules.json`: persisted rules/examples

Recommended future additions:
- `father_gateway.py` using Telethon
- `automation_runtime.py` for stateful multi-step execution
- `api_server.py` for HTTP endpoints if external gateway mode is used
- review queue and audit logs
