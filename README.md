# mybot

A local, tool-using personal assistant for Windows. It talks to any OpenAI-compatible
LLM (DeepSeek, OpenAI, OpenRouter, Groq, Ollama, ...) and can read/write files, run
shell commands, control the desktop, manage scheduled tasks, and solve GitHub issues.

## Requirements

- Python 3.10+ (tested on 3.13)
- An API key for an OpenAI-compatible provider (or a local Ollama)

## Setup

```powershell
git clone https://github.com/AyinkxLab/mybot.git
cd mybot
python -m pip install -r requirements.txt
```

Then start it and connect a provider:

```powershell
python main.py
you> /connect
```

`/connect` asks for the provider (default `deepseek`), your API key, and then lists the
models the provider actually offers for your key so you can pick one. Credentials are
saved to `.mybot_config.json` (gitignored). You can also set `LLM_API_KEY`,
`LLM_BASE_URL`, and `LLM_MODEL` in a `.env` file instead — see `.env.example`.

## Running it

- **Full-screen TUI (default):** `python tui.py`, or type `mybot` if the folder is on your `PATH`.
- **Plain CLI:** `python main.py` (or `mybot-cli`).
- **Desktop app:** `mybot-gui.cmd` (or the desktop shortcut) opens a tkinter chat window.

### TUI

Opens on an opencode-style home screen: a centered logo, a centered prompt box, the active
agent mode + model line, key hints, and a version tag. The first message switches to the chat
view: top status bar (model, agent mode, token in/out, estimated cost), scrollable chat with
per-role colored borders, streaming markdown, inline tool-call rows, an approval modal, and a
live **todo** sidebar the model keeps updated.

Keys:
`tab` agent mode · `ctrl+p` command palette · `ctrl+t` theme · `ctrl+o` toggle todos ·
`ctrl+n` new session · `esc` cancel run · `ctrl+c` quit

Commands: `/connect`, `/models`, `/theme`, `/mode`, `/reset`, `/new`, `/exit` (`/help` in the TUI).

Agent modes: **build** (default, full access) and **plan** (read-only; the model plans but does
not modify files or run mutating commands). Themes: `mybot`, `dracula`, `tokyo-night`, `gruvbox`,
`nord`, plus Textual's built-ins.

The TUI is built with [Textual](https://textual.textualize.io/) (`textual` + `rich` in
`requirements.txt`). The model uses a `todo_write` tool to plan multi-step work; those items
appear in the sidebar as they change.

> This is an opencode-*style* interface, not a pixel-perfect clone of opencode's Go/Bubble Tea UI.

## Configuration (`.env`)

See `.env.example` for the full list. Highlights:

| Variable | Purpose |
|----------|---------|
| `BOT_WORKSPACE` | Root the file/shell tools may use. Default `workspace/`. |
| `REQUIRE_APPROVAL` | When `true`, pushes / PRs / GitHub writes / scheduled tasks pause for approval. |
| `ALLOW_SHELL` | Set `false` to disable shell execution entirely. |
| `GITHUB_TOKEN` | Fine-grained PAT (Contents + Issues + Pull requests) for issue solving. |
| `ALLOW_PRIVATE_HTTP` | Allow `http_get` to reach localhost/private IPs (SSRF risk). |
| `TELEGRAM_ALLOWED_IDS` / `DISCORD_ALLOWED_IDS` | User IDs allowed to use the chat adapters. |

### Full-machine access

To give the bot more reach, set `BOT_WORKSPACE=C:\` and `REQUIRE_APPROVAL=false`.
This is a powerful and risky configuration and is entirely at your own discretion.

## Tools

`read_file`, `write_file`, `list_dir`, `run_shell`, `http_get`, `github_request`,
`launch_app`, `gui_click`, `gui_type`, `gui_hotkey`, `gui_screenshot`,
`schedule_task`, `list_tasks`, `delete_task`.

## Chat adapters

```powershell
python adapters\telegram_bot.py   # set TELEGRAM_TOKEN and TELEGRAM_ALLOWED_IDS
python adapters\discord_bot.py    # set DISCORD_TOKEN and DISCORD_ALLOWED_IDS
```
Discord requires the privileged **Message Content Intent** in the developer portal.
Always set the allowlists — otherwise anyone who finds the bot can run commands on
your machine.

## Safety notes

- The LLM still applies its own safety behavior; this project does not (and cannot)
  remove that.
- `run_shell` executes real commands. Keep `REQUIRE_APPROVAL=true` and a sandboxed
  `BOT_WORKSPACE` unless you fully accept the risk.
- The destructive-command gate is a best-effort blocklist, not a hard sandbox.
- Use a narrowly scoped GitHub token. Never a classic `repo`-scope token.

## License

MIT — see [LICENSE](LICENSE).
