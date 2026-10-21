# Installable ChatGPT Skill

This folder contains the workflow layer for RAVICOM Mail. It does not connect to a mailbox by itself. Install the separate RAVICOM Mail MCP app to provide live mailbox tools.

To make an upload archive, zip this folder so `SKILL.md` is at the archive root. In eligible ChatGPT workspaces open **Plugins → Skills → Create → Upload from your computer** and select the ZIP. Skills availability and custom MCP server access depend on the ChatGPT workspace plan and its admin settings.

## Smoke prompts

- “Show me a short overview of my Yandex mailbox.”
- “Find unread mail from the last month from Госуслуги and summarize the subjects.”
- “Preview read messages in Inbox older than one year. Do not move anything yet.”
- After inspecting a preview, test the second step with: “I approve this exact preview. Move these messages to Trash.”

Expected behavior: the skill uses live MCP tools only if the app is connected; it displays a cleanup preview first, asks for approval, and only then calls `execute_cleanup`.
