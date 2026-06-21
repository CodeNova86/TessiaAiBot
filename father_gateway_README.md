Father gateway quick start

This runner connects to the father's personal Telegram account using Telethon and auto-replies only in private chats for whitelisted users.

Required environment variables:
- `FATHER_AUTO_REPLY_ENABLED=true`
- `TELETHON_API_ID=...`
- `TELETHON_API_HASH=...`
- optional: `TELETHON_SESSION_NAME=father_session`

Whitelist file:
- `father_whitelist.json`

Current scope:
- private chats only
- text messages only
- whitelist only
- replies with the current Tessia AI brain

Run:
- `python father_gateway.py`

First run notes:
- Telethon will ask for the father's phone number and login code
- if 2FA is enabled, it will also ask for the password

Recommended next safeguards:
- cooldown per contact
- pause if father manually replies in a chat
- review mode before sending
