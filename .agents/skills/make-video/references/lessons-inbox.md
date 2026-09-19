# Lessons inbox — NOT rules; waiting for Claude to verify

Render-only agents (agy, codex) append new lessons here instead of editing the other references.
Once `videotool agent lesson` exists, use it (it appends here and messages the user). Until then
append by hand AND tell the user in the session. When the user asks, Claude verifies each entry
against code/logs and moves it into the right reference, then deletes it from this file.

Entry format:

```
## YYYY-MM-DD <agent> <episode slug>
- What happened:
- Evidence (log line, file, command output):
- Suggested rule:
```
