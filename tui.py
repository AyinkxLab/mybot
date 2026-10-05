import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, Markdown, Select, Static

from agent import Agent
from auth import PROVIDERS, is_configured, list_models, save_auth
from config import REQUIRE_APPROVAL, WORKSPACE
from tools import get_todos, set_approval_handler


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


HELP = """[b]commands[/]
  /connect   set provider, key and model
  /models    switch the model
  /reset     clear conversation history
  /help      show this
  /exit      quit

Just type a task and press Enter. The model plans with a todo list, and tool calls appear inline."""


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
        body = self.query_one(Markdown)
        body.update(text or "")

    def append(self, chunk: str) -> None:
        self._text += chunk
        body = self.query_one(Markdown)
        body.update(self._text)


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


class ApprovalScreen(ModalScreen):
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


class ConnectScreen(ModalScreen):
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


class MybotApp(App):
    CSS = """
    Screen { background: #0b0b12; color: #c9d1d9; }
    #topbar { height: 1; background: #16161f; padding: 0 1; }
    #main { height: 1fr; }
    #chat { width: 1fr; padding: 0 1; }
    #todos { width: 42; border-left: solid #1f2937; padding: 0 1; }
    #todo-title { text-style: bold; color: #c4b5fd; height: 1; }
    .msg { margin: 0 0 1 0; padding: 0 0 0 1; height: auto; }
    .msg.you { border-left: thick #22c55e; }
    .msg.mybot { border-left: thick #818cf8; }
    .role { height: 1; text-style: bold; color: #6b7280; }
    .msg.you .role { color: #22c55e; }
    .msg.mybot .role { color: #818cf8; }
    .tool { color: #eab308; padding: 0 0 0 2; height: auto; }
    #prompt { dock: bottom; border: tall #3b3b52; background: #12121a; }
    #prompt:focus { border: tall #818cf8; }
    ApprovalScreen { align: center middle; }
    #approval { width: 72; height: auto; border: thick #eab308; background: #16161f; padding: 1 2; }
    #approval-title { text-style: bold; color: #eab308; }
    #approval-buttons { height: auto; align: right middle; }
    ConnectScreen { align: center middle; }
    #connect { width: 76; height: auto; border: thick #818cf8; background: #16161f; padding: 1 2; }
    #connect-title { text-style: bold; color: #c4b5fd; }
    .field-label { color: #9ca3af; margin: 1 0 0 0; }
    #model-row { height: auto; }
    #model-row Select { width: 1fr; }
    #connect-buttons { height: auto; align: right middle; margin: 1 0 0 0; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "quit"),
        Binding("ctrl+r", "reset", "reset"),
        Binding("ctrl+t", "toggle_todos", "todos"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.agent = None
        self.busy = False
        self._last_tool = None

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Horizontal(id="main"):
            yield VerticalScroll(id="chat")
            yield TodoPanel(id="todos")
        yield Input(placeholder="Ask mybot anything...", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        set_approval_handler(self._approve)
        if is_configured():
            try:
                self.agent = Agent()
            except Exception as exc:
                self._note(f"error: {exc}")
        self._refresh_topbar()
        self.query_one(TodoPanel).refresh_todos(get_todos())
        if self.agent is None:
            self._note("Not connected. Type /connect to add your API key.")
        else:
            self._note(f"Connected: {self.agent.model}. Ask me anything, or type /help.")
        self.query_one("#prompt", Input).focus()

    def _refresh_topbar(self) -> None:
        model = self.agent.model if self.agent else "not connected"
        bar = Text()
        bar.append(" mybot ", style="bold #0b0b12 on #c4b5fd")
        bar.append(f"  {model}", style="#9ca3af")
        bar.append("   " + str(WORKSPACE), style="#4b5563")
        if self.busy:
            bar.append("   working…", style="italic #eab308")
        self.query_one("#topbar", Static).update(bar)

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
        self._refresh_topbar()
        self._run_agent(text, assistant)

    def _command(self, text: str) -> None:
        command = text.split()[0].lower()
        if command in {"/exit", "/quit"}:
            self.exit()
        elif command == "/help":
            self._note(HELP)
        elif command == "/reset":
            if self.agent is not None:
                self.agent.reset()
            self._note("History cleared.")
        elif command in {"/connect", "/models"}:
            self._connect()
        else:
            self._note(f"Unknown command: {command}")

    def _connect(self) -> None:
        def done(saved) -> None:
            if not saved:
                return
            try:
                self.agent = Agent()
            except Exception as exc:
                self._note(f"error: {exc}")
                return
            self._refresh_topbar()
            self._note(f"Connected: {self.agent.model}")

        self.push_screen(ConnectScreen(), done)

    @work(thread=True)
    def _run_agent(self, text: str, assistant: MessageView) -> None:
        if self.agent is None:
            self.call_from_thread(assistant.set_text, "Not connected - type /connect first.")
            self.call_from_thread(self._finish)
            return
        try:
            for event in self.agent.respond_stream(text):
                kind = event["type"]
                if kind == "delta":
                    self.call_from_thread(assistant.append, event["text"])
                elif kind == "tool":
                    self.call_from_thread(self._add_tool, event["name"], event["args"])
                elif kind == "tool_result":
                    self.call_from_thread(self._tool_result, event["result"])
                    if event["name"] == "todo_write":
                        self.call_from_thread(self._refresh_todos)
                elif kind == "final":
                    self.call_from_thread(
                        assistant.set_text, event["text"] or assistant._text
                    )
        except Exception as exc:
            self.call_from_thread(assistant.set_text, f"error: {exc}")
        finally:
            self.call_from_thread(self._finish)

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

    def action_toggle_todos(self) -> None:
        panel = self.query_one(TodoPanel)
        panel.display = not panel.display


def main() -> None:
    MybotApp().run()


if __name__ == "__main__":
    main()
