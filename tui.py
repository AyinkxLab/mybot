import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Markdown, OptionList, Select, Static
from textual.widgets.option_list import Option

from agent import Agent
from auth import (
    PROVIDERS,
    is_configured,
    list_models,
    load_auth,
    save_auth,
)
from config import REQUIRE_APPROVAL, SYSTEM_PROMPT, WORKSPACE
from tools import get_todos, set_approval_handler, todo_write


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


PRICING = {
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}

MODES = {
    "build": "",
    "plan": (
        "\n\nMODE: plan. Investigate and produce a plan with todo_write, but do NOT modify "
        "files, run mutating shell commands, push, or create scheduled tasks. Wait for the "
        "user to switch to build mode before making any changes."
    ),
}

COMMANDS = [
    ("connect a provider", "connect"),
    ("switch model", "models"),
    ("change theme", "theme"),
    ("change agent mode", "mode"),
    ("new session", "new"),
    ("clear history", "reset"),
    ("help", "help"),
    ("quit", "quit"),
]

HELP = """[b]commands[/]
  /connect   set provider, key and model
  /models    switch the model
  /theme     change theme
  /mode      switch agent mode (build / plan)
  /reset     clear conversation history
  /help      show this
  /exit      quit

[b]keys[/]
  tab        agent mode      ctrl+p   command palette
  ctrl+t     theme           ctrl+o   toggle todo panel
  ctrl+n     new session      esc      cancel current run
  ctrl+c     quit

The model plans multi-step work with a todo list shown in the sidebar."""


class MessageView(Vertical):
    def __init__(self, role: str, text: str = "") -> None:
        super().__init__(classes=f"msg {role}")
        self._text = text
        self.role_name = role

    def compose(self) -> ComposeResult:
        yield Static(self.role_name, classes="role")
        yield Markdown(self._text, classes="body")

    def set_text(self, text: str) -> None:
        self._text = text
        self.query_one(Markdown).update(text or "")

    def append(self, chunk: str) -> None:
        self._text += chunk
        self.query_one(Markdown).update(self._text)


class ToolView(Static):
    def __init__(self, name: str, args: str) -> None:
        super().__init__(classes="tool")
        self.tool_name = name
        self.tool_args = args
        self.update(f"⚙ {name}  {_short(args)}")

    def set_result(self, result: str) -> None:
        self.update(
            f"⚙ {self.tool_name}  {_short(self.tool_args, 60)}  →  {_short(result, 90)}"
        )


class TodoPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("todo", id="todo-title")
        yield Static("", id="todo-body")

    def refresh_todos(self, todos: list) -> None:
        body = self.query_one("#todo-body", Static)
        if not todos:
            self.display = False
            return
        self.display = True
        text = Text()
        for item in todos:
            status = item["status"]
            if status == "completed":
                text.append("✔ ", style="green")
                text.append(item["content"] + "\n", style="dim strike")
            elif status == "in_progress":
                text.append("◐ ", style="yellow")
                text.append(item["content"] + "\n", style="bold white")
            else:
                text.append("○ ", style="grey50")
                text.append(item["content"] + "\n", style="grey70")
        body.update(text)


class Chooser(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, title: str, options: list) -> None:
        super().__init__()
        self.title = title
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            yield Static(self.title, id="palette-title")
            yield OptionList(
                *(Option(label, id=str(index)) for index, (label, _) in enumerate(self.options)),
                id="palette-list",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.options[int(event.option.id)][1])

    def action_cancel(self) -> None:
        self.dismiss(None)


class ApprovalScreen(ModalScreen):
    BINDINGS = [Binding("escape", "deny", "deny")]

    def __init__(self, action: str) -> None:
        super().__init__()
        self.action = action

    def compose(self) -> ComposeResult:
        with Vertical(id="approval"):
            yield Static("approval needed", id="approval-title")
            yield Static(self.action, id="approval-body")
            with Horizontal(id="approval-buttons"):
                yield Button("Deny", variant="error", id="deny")
                yield Button("Allow", variant="success", id="allow")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow")

    def action_deny(self) -> None:
        self.dismiss(False)


class ConnectScreen(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="connect"):
            yield Static("connect provider", id="connect-title")
            yield Static("provider", classes="field-label")
            yield Select(
                [(name, name) for name in PROVIDERS],
                value="deepseek",
                allow_blank=False,
                id="provider",
            )
            yield Static("API key", classes="field-label")
            yield Input(password=True, placeholder="sk-...", id="key")
            yield Static("base URL", classes="field-label")
            yield Input(value=PROVIDERS["deepseek"]["base_url"], id="base_url")
            yield Static("model", classes="field-label")
            with Horizontal(id="model-row"):
                yield Select(
                    [(m, m) for m in PROVIDERS["deepseek"]["models"]],
                    value=PROVIDERS["deepseek"]["models"][0],
                    allow_blank=False,
                    id="model",
                )
                yield Button("Fetch", id="fetch")
            with Horizontal(id="connect-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="success", id="save")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "provider":
            return
        preset = PROVIDERS.get(event.value, {})
        self.query_one("#base_url", Input).value = preset.get("base_url", "")
        models = preset.get("models", [])
        select = self.query_one("#model", Select)
        select.set_options([(m, m) for m in models])
        if models:
            select.value = models[0]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "cancel":
            self.dismiss(False)
        elif button == "fetch":
            key = self.query_one("#key", Input).value.strip()
            url = self.query_one("#base_url", Input).value.strip()
            if not key or not url:
                return
            models = list_models(url, key)
            if models:
                select = self.query_one("#model", Select)
                select.set_options([(m, m) for m in models])
                select.value = models[0]
        elif button == "save":
            key = self.query_one("#key", Input).value.strip()
            provider = self.query_one("#provider", Select).value
            base_url = self.query_one("#base_url", Input).value.strip()
            model = self.query_one("#model", Select).value
            if not key or model == Select.BLANK:
                return
            save_auth(
                {"provider": provider, "base_url": base_url, "api_key": key, "model": model}
            )
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class MybotApp(App):
    CSS = """
    Screen { background: $background; color: $foreground; }
    #topbar { height: 1; background: $panel; padding: 0 1; }
    #main { height: 1fr; }
    #chat { width: 1fr; padding: 0 1; }
    #todos { width: 42; border-left: solid $surface; padding: 0 1; }
    #todo-title { text-style: bold; color: $primary; height: 1; }
    .msg { margin: 0 0 1 0; padding: 0 0 0 1; height: auto; }
    .msg.you { border-left: thick $success; }
    .msg.mybot { border-left: thick $primary; }
    .role { height: 1; text-style: bold; color: $text-muted; }
    .msg.you .role { color: $success; }
    .msg.mybot .role { color: $primary; }
    .tool { color: $warning; padding: 0 0 0 2; height: auto; }
    #prompt { dock: bottom; border: tall $surface; background: $panel; }
    #prompt:focus { border: tall $primary; }
    ApprovalScreen { align: center middle; }
    #approval { width: 72; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    #approval-title { text-style: bold; color: $warning; }
    #approval-buttons { height: auto; align: right middle; }
    ConnectScreen { align: center middle; }
    #connect { width: 76; height: auto; border: thick $primary; background: $surface; padding: 1 2; }
    #connect-title { text-style: bold; color: $primary; }
    .field-label { color: $text-muted; margin: 1 0 0 0; }
    #model-row { height: auto; }
    #model-row Select { width: 1fr; }
    #connect-buttons { height: auto; align: right middle; margin: 1 0 0 0; }
    Chooser { align: center middle; }
    #palette { width: 60; height: auto; max-height: 80%; border: thick $primary; background: $surface; padding: 1 2; }
    #palette-title { text-style: bold; color: $primary; margin: 0 0 1 0; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "quit"),
        Binding("tab", "mode", "mode"),
        Binding("ctrl+p", "palette", "palette"),
        Binding("ctrl+t", "theme", "theme"),
        Binding("ctrl+o", "toggle_todos", "todos"),
        Binding("ctrl+n", "new", "new"),
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+r", "reset", "reset", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.agent = None
        self.busy = False
        self.mode = "build"
        self.tokens_in = 0
        self.tokens_out = 0
        self._last_tool = None
        self._cancel = threading.Event()

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Horizontal(id="main"):
            yield VerticalScroll(id="chat")
            yield TodoPanel(id="todos")
        yield Input(placeholder="Ask mybot anything...", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._register_themes()
        self.theme = "mybot"
        set_approval_handler(self._approve)
        if is_configured():
            try:
                self.agent = Agent(system_prompt=self._system_prompt())
            except Exception as exc:
                self._note(f"error: {exc}")
        self._refresh_topbar()
        self.query_one(TodoPanel).refresh_todos(get_todos())
        if self.agent is None:
            self._note("Not connected. Type /connect to add your API key.")
        else:
            self._note(f"Connected: {self.agent.model}. Type /help for shortcuts.")
        self.query_one("#prompt", Input).focus()

    def _register_themes(self) -> None:
        self.register_theme(
            Theme(
                "mybot",
                primary="#c4b5fd",
                secondary="#818cf8",
                accent="#22d3ee",
                background="#0b0b12",
                surface="#16161f",
                panel="#16161f",
                success="#22c55e",
                warning="#eab308",
                error="#ef4444",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "dracula",
                primary="#bd93f9",
                secondary="#ff79c6",
                accent="#8be9fd",
                background="#282a36",
                surface="#343746",
                panel="#21222c",
                success="#50fa7b",
                warning="#f1fa8c",
                error="#ff5555",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "tokyo-night",
                primary="#7aa2f7",
                secondary="#bb9af7",
                accent="#7dcfff",
                background="#1a1b26",
                surface="#24283b",
                panel="#16161e",
                success="#9ece6a",
                warning="#e0af68",
                error="#f7768e",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "gruvbox",
                primary="#fabd2f",
                secondary="#b8bb26",
                accent="#83a598",
                background="#282828",
                surface="#3c3836",
                panel="#1d2021",
                success="#b8bb26",
                warning="#fabd2f",
                error="#fb4934",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "nord",
                primary="#88c0d0",
                secondary="#81a1c1",
                accent="#8fbcbb",
                background="#2e3440",
                surface="#3b4252",
                panel="#2e3440",
                success="#a3be8c",
                warning="#ebcb8b",
                error="#bf616a",
                dark=True,
            )
        )

    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT + MODES.get(self.mode, "")

    def _refresh_topbar(self) -> None:
        model = self.agent.model if self.agent else "not connected"
        bar = Text()
        bar.append(" mybot ", style="bold #0b0b12 on #c4b5fd")
        bar.append(f"  {model}", style="#9ca3af")
        bar.append(f"  [{self.mode}]", style="#c4b5fd")
        if self.tokens_in or self.tokens_out:
            bar.append(
                f"   ↑{_fmt_tokens(self.tokens_in)} ↓{_fmt_tokens(self.tokens_out)}",
                style="#6b7280",
            )
            cost = self._cost()
            if cost is not None:
                bar.append(f"  ${cost:.4f}", style="#6b7280")
        if self.busy:
            bar.append("   working…", style="italic #eab308")
        self.query_one("#topbar", Static).update(bar)

    def _cost(self) -> float:
        model = self.agent.model if self.agent else ""
        price = PRICING.get(model)
        if price is None:
            return None
        return self.tokens_in / 1e6 * price[0] + self.tokens_out / 1e6 * price[1]

    def _scroll_end(self) -> None:
        try:
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _note(self, text: str) -> None:
        self.query_one("#chat", VerticalScroll).mount(MessageView("mybot", text))
        self._scroll_end()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.query_one("#prompt", Input).value = ""
        if not text or self.busy:
            return
        if text.startswith("/"):
            self._command(text)
            return
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(MessageView("you", text))
        assistant = MessageView("mybot", "")
        chat.mount(assistant)
        self._scroll_end()
        self.busy = True
        self._cancel.clear()
        self._refresh_topbar()
        self._run_agent(text, assistant)

    def _command(self, text: str) -> None:
        command = text.split()[0].lower()
        mapping = {
            "/connect": "connect",
            "/models": "models",
            "/theme": "theme",
            "/mode": "mode",
            "/reset": "reset",
            "/help": "help",
            "/new": "new",
            "/exit": "quit",
            "/quit": "quit",
        }
        action = mapping.get(command)
        if action is None:
            self._note(f"Unknown command: {command}")
        else:
            self._run_command(action)

    def _run_command(self, action: str) -> None:
        if action == "connect":
            self._connect()
        elif action == "models":
            self._choose_model()
        elif action == "theme":
            self._choose_theme()
        elif action == "mode":
            self._choose_mode()
        elif action == "new":
            self.action_new()
        elif action == "reset":
            self.action_reset()
        elif action == "help":
            self._note(HELP)
        elif action == "quit":
            self.exit()

    def _connect(self) -> None:
        def done(saved) -> None:
            if not saved:
                return
            try:
                self.agent = Agent(system_prompt=self._system_prompt())
            except Exception as exc:
                self._note(f"error: {exc}")
                return
            self._refresh_topbar()
            self._note(f"Connected: {self.agent.model}")

        self.push_screen(ConnectScreen(), done)

    def _choose_model(self) -> None:
        auth = load_auth()
        if not auth.get("api_key"):
            self._note("Connect first with /connect.")
            return
        models = list_models(auth.get("base_url", ""), auth["api_key"])
        if not models:
            models = PROVIDERS.get(auth.get("provider", ""), {}).get("models", [])
        if not models:
            self._note("No models found.")
            return

        def done(choice) -> None:
            if not choice:
                return
            auth["model"] = choice
            save_auth(auth)
            try:
                self.agent = Agent(system_prompt=self._system_prompt())
            except Exception as exc:
                self._note(f"error: {exc}")
                return
            self._refresh_topbar()
            self._note(f"Model set to {choice}")

        self.push_screen(Chooser("select model", [(m, m) for m in models]), done)

    def _choose_theme(self) -> None:
        names = sorted({*self.available_themes.keys()})

        def done(choice) -> None:
            if choice:
                self.theme = choice
                self._note(f"Theme: {choice}")

        self.push_screen(Chooser("select theme", [(n, n) for n in names]), done)

    def _choose_mode(self) -> None:
        def done(choice) -> None:
            if not choice:
                return
            self.mode = choice
            if self.agent is not None:
                self.agent.messages[0]["content"] = self._system_prompt()
            self._refresh_topbar()
            self._note(f"Agent mode: {choice}")

        self.push_screen(
            Chooser("select agent mode", [(m, m) for m in MODES]), done
        )

    @work(thread=True)
    def _run_agent(self, text: str, assistant: MessageView) -> None:
        if self.agent is None:
            self.call_from_thread(assistant.set_text, "Not connected - type /connect first.")
            self.call_from_thread(self._finish)
            return
        try:
            for event in self.agent.respond_stream(text):
                if self._cancel.is_set():
                    self.call_from_thread(assistant.append, "\n\n_\\[cancelled]_")
                    break
                kind = event["type"]
                if kind == "delta":
                    self.call_from_thread(assistant.append, event["text"])
                elif kind == "tool":
                    self.call_from_thread(self._add_tool, event["name"], event["args"])
                elif kind == "tool_result":
                    self.call_from_thread(self._tool_result, event["result"])
                    if event["name"] == "todo_write":
                        self.call_from_thread(self._refresh_todos)
                elif kind == "usage":
                    self.call_from_thread(
                        self._add_usage, event.get("input", 0), event.get("output", 0)
                    )
                elif kind == "final":
                    self.call_from_thread(
                        assistant.set_text, event["text"] or assistant._text
                    )
        except Exception as exc:
            self.call_from_thread(assistant.set_text, f"error: {exc}")
        finally:
            self.call_from_thread(self._finish)

    def _add_usage(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self._refresh_topbar()

    def _add_tool(self, name: str, args: str) -> None:
        view = ToolView(name, args)
        self._last_tool = view
        self.query_one("#chat", VerticalScroll).mount(view)
        self._scroll_end()

    def _tool_result(self, result: str) -> None:
        if self._last_tool is not None:
            self._last_tool.set_result(result)
        self._scroll_end()

    def _refresh_todos(self) -> None:
        self.query_one(TodoPanel).refresh_todos(get_todos())

    def _finish(self) -> None:
        self.busy = False
        self._refresh_topbar()
        self._scroll_end()
        self.query_one("#prompt", Input).focus()

    def _approve(self, action: str) -> bool:
        event = threading.Event()
        result = {"ok": False}

        def ask() -> None:
            def done(ok) -> None:
                result["ok"] = bool(ok)
                event.set()

            self.push_screen(ApprovalScreen(action), done)

        self.call_from_thread(ask)
        event.wait()
        return result["ok"]

    def action_reset(self) -> None:
        if self.agent is not None:
            self.agent.reset()
        self._note("History cleared.")

    def action_new(self) -> None:
        if self.agent is not None:
            self.agent.reset()
        self.query_one("#chat", VerticalScroll).remove_children()
        todo_write([])
        self.query_one(TodoPanel).refresh_todos([])
        self.tokens_in = 0
        self.tokens_out = 0
        self._note("New session.")
        self._refresh_topbar()

    def action_toggle_todos(self) -> None:
        panel = self.query_one(TodoPanel)
        panel.display = not panel.display

    def action_theme(self) -> None:
        self._choose_theme()

    def action_mode(self) -> None:
        self._choose_mode()

    def action_palette(self) -> None:
        def done(choice) -> None:
            if choice:
                self._run_command(choice)

        self.push_screen(Chooser("commands", COMMANDS), done)

    def action_cancel(self) -> None:
        if self.busy:
            self._cancel.set()
            self._note("Cancelling…")


def main() -> None:
    MybotApp().run()


if __name__ == "__main__":
    main()
