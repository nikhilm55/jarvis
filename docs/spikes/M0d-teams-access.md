# M0d — Can Jarvis read and send Teams messages?

**Hypothesis:** Microsoft Graph, through an M365 MCP server, can list unread chats and send a message with delegated permissions *if* the tenant allows user consent (OQ-001). If it doesn't, UI Automation on the Teams desktop app (Windows) can at least read the chat list and unread badges and type into the compose box.
**FRS refs:** FR-MCP-11, §6.2–6.4 scenarios, FRS §12.1 Graph risk, OQ-001.
**Method:**
1. Graph path: sign in with the owner's work account through the M365 MCP device-code flow. Record whether consent is granted, needs admin, or is blocked. If granted: list chats with unread messages and send a test message to yourself (self-chat).
2. UI-Automation path (Windows): inspect the new Teams accessibility tree, then read the chat list, open a chat and type a draft (no send).
3. Record per path: works / blocked / partial, latency, and what the user would have to do.
**Pass bar:** at least one path supports S2 (read unread) and S3 (compose and send) end to end, or a documented fallback with clear remedy text for the user.
**Time-box:** 6 h. Blocked on the owner's sign-in and OQ-001.

## Result

_Pending._

## Decision

_Pending._
