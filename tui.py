import random
import re
import threading
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Input, Markdown, OptionList, Select, Static, TextArea
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
from tools import (
    TOOL_SPECS,
    get_todos,
    read_file,
    run_shell,
    set_approval_handler,
    todo_write,
)


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _reasoning_summary(text: str):
    content = text.strip()
    match = re.match(r"^\*\*([^*\n]+)\*\*(?:\r?\n\r?\n|$)", content)
    if not match:
        return None, content
    return match.group(1).strip(), content[match.end():].strip()


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

CONTEXT_WINDOWS = {
    "deepseek-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
}
DEFAULT_CONTEXT = 128_000

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
    ("toggle thinking blocks", "thinking"),
    ("toggle tool details", "details"),
    ("compact session", "compact"),
    ("export conversation", "export"),
    ("switch session", "sessions"),
    ("undo last turn", "undo"),
    ("redo last turn", "redo"),
    ("new session", "new"),
    ("clear history", "reset"),
    ("help", "help"),
    ("quit", "quit"),
]

HELP = """[b]commands[/]
  /connect     set provider, key and model
  /models      switch the model
  /theme       change theme (alias /themes)
  /mode        switch agent mode (build / plan)
  /thinking    expand/collapse reasoning blocks
  /details     expand/collapse tool output
  /compact     summarize the session (alias /summarize)
  /export      write the conversation to a Markdown file
  /sessions    switch between sessions (aliases /resume /continue)
  /undo        remove the last turn (alias ctrl+x u)
  /redo        restore an undone turn (alias ctrl+x r)
  /new         new session (alias /clear)
  /reset       clear conversation history
  /help        show this
  /exit        quit

[b]prefixes[/]
  !cmd         run a shell command
  @file        attach file contents to your message

[b]keys[/]
  enter   send           ctrl+j  newline in the prompt
  tab     agent mode     ctrl+p  command palette    ctrl+o  toggle sidebar
  ctrl+x  leader (n l u r t m c x q)                 ctrl+t  theme
  ctrl+n  new session    esc     cancel run          ctrl+c  quit

The model plans multi-step work with a todo list shown in the sidebar."""

BANNER = [
    "███╗   ███╗██╗   ██╗██████╗  ██████╗ ████████╗",
    "████╗ ████║╚██╗ ██╔╝██╔══██╗██╔═══██╗╚══██╔══╝",
    "██╔████╔██║ ╚████╔╝ ██████╔╝██║   ██║   ██║   ",
    "██║╚██╔╝██║  ╚██╔╝  ██╔══██╗██║   ██║   ██║   ",
    "██║ ╚═╝ ██║   ██║   ██████╔╝╚██████╔╝   ██║   ",
    "╚═╝     ╚═╝   ╚═╝   ╚═════╝  ╚═════╝    ╚═╝   ",
]
ACCENT = "#5c9cf5"
ACCENT_SOFT = "#5c9cf5"
TEXT_COLOR = "#eeeeee"
MUTED = "#808080"
VERSION = "mybot 0.1.0"
HOME_PLACEHOLDERS = [
    "Fix a TODO in the codebase",
    "What is the tech stack of this project?",
    "Fix broken tests",
]
NO_MODELS_TIP = "Run {highlight}/connect{/highlight} to add an AI provider and start coding"
TIPS = [
    "Type {highlight}@{/highlight} followed by a filename to attach files",
    "Start a message with {highlight}!{/highlight} to run shell commands (e.g., {highlight}!ls -la{/highlight})",
    "Use {highlight}/undo{/highlight} to revert the last turn",
    "Use {highlight}/redo{/highlight} to restore an undone turn",
    "Use {highlight}/models{/highlight} to switch between available AI models",
    "Use {highlight}/themes{/highlight} to switch themes",
    "Use {highlight}/new{/highlight} to start a fresh session",
    "Use {highlight}/sessions{/highlight} to list and continue sessions",
    "Run {highlight}/compact{/highlight} to summarize long sessions",
    "Use {highlight}/export{/highlight} to save the conversation as Markdown",
    "Run {highlight}/connect{/highlight} to add an AI provider",
    "Press {highlight}tab{/highlight} to switch between Build and Plan agents",
    "Set {highlight}REQUIRE_APPROVAL=true{/highlight} to gate risky commands",
    "Use {highlight}/thinking{/highlight} to expand or collapse reasoning",
    "Press {highlight}esc{/highlight} to stop the AI mid-response",
]


def _logo() -> Text:
    muted, bright = MUTED, TEXT_COLOR
    text = Text(justify="center")
    for line in BANNER:
        half = len(line) // 2
        text.append(line[:half], style=f"bold {muted}")
        text.append(line[half:], style=f"bold {bright}")
        text.append("\n")
    return text


def _placeholder_text() -> str:
    return f'Ask anything… "{random.choice(HOME_PLACEHOLDERS)}"'


def _parse_tip(tip: str):
    parts = []
    index = 0
    for match in re.finditer(r"\{highlight\}(.*?)\{/highlight\}", tip):
        if match.start() > index:
            parts.append((tip[index : match.start()], False))
        parts.append((match.group(1), True))
        index = match.end()
    if index < len(tip):
        parts.append((tip[index:], False))
    return parts


def _hint_text() -> Text:
    text = Text(justify="right")
    text.append("tab", style=TEXT_COLOR)
    text.append(" agents      ", style=MUTED)
    text.append("ctrl+p", style=TEXT_COLOR)
    text.append(" commands", style=MUTED)
    return text


def _tip_text(connected: bool = True) -> Text:
    tip = NO_MODELS_TIP if not connected else random.choice(TIPS)
    text = Text(justify="center")
    text.append("● Tip  ", style=WARNING_COLOR)
    for part, highlight in _parse_tip(tip):
        text.append(part, style=TEXT_COLOR if highlight else MUTED)
    return text


class PromptArea(TextArea):
    class Submitted(Message):
        def __init__(self, area: "PromptArea", value: str) -> None:
            super().__init__()
            self.area = area
            self.value = value

    def __init__(self, placeholder: str = "", id: str | None = None) -> None:
        super().__init__(
            theme="css",
            soft_wrap=True,
            compact=True,
            placeholder=placeholder,
            show_line_numbers=False,
            highlight_cursor_line=False,
            id=id,
        )

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self, self.text))
            return
        if event.key in ("ctrl+j", "shift+enter"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)


class Session:
    def __init__(self, agent=None, title: str = "new session") -> None:
        self.agent = agent
        self.title = title
        self.records: list = []
        self.tokens_in = 0
        self.tokens_out = 0
        self.context_tokens = 0


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
    def __init__(self, name: str, args: str, detailed: bool = False) -> None:
        super().__init__(classes="tool")
        self.tool_name = name
        self.tool_args = args
        self._result = ""
        self._expanded = detailed
        self._refresh_content()

    def _refresh_content(self) -> None:
        text = Text()
        text.append(f"⚙ {self.tool_name}", style=f"bold {WARNING_COLOR}")
        text.append(f"  {_short(self.tool_args, 70)}\n", style=MUTED_COLOR)
        result = (self._result or "").strip()
        if result:
            lines = result.splitlines()
            limit = 200 if self._expanded else 3
            for line in lines[:limit]:
                text.append("  " + line + "\n", style="#a0a0a0")
            if len(lines) > limit:
                text.append(
                    f"  … {len(lines) - limit} more lines · click to expand\n",
                    style="#5c5c5c",
                )
        self.update(text)

    def set_result(self, result: str) -> None:
        self._result = result
        self._refresh_content()

    def set_detailed(self, detailed: bool) -> None:
        self._expanded = detailed
        self._refresh_content()

    def on_click(self) -> None:
        self._expanded = not self._expanded
        self._refresh_content()


WARNING_COLOR = "#f5a742"
MUTED_COLOR = "#808080"


class ThinkingView(Static):
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, expanded: bool = False) -> None:
        super().__init__(classes="thinking")
        self._text = ""
        self._start = time.monotonic()
        self._elapsed = 0.0
        self._done = False
        self._expanded = expanded
        self._i = 0
        self._timer = None
        self._refresh_content()

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.12, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _tick(self) -> None:
        if not self._done:
            self._i += 1
            self._refresh_content()

    def _refresh_content(self) -> None:
        title, body = _reasoning_summary(self._text)
        text = Text()
        if not self._done:
            frame = self.FRAMES[self._i % len(self.FRAMES)]
            head = f"{frame} Thinking" + (f": {title}" if title else "")
        else:
            mark = "- " if self._expanded else "+ "
            head = (
                f"{mark}Thought"
                + (f": {title}" if title else "")
                + f" · {self._elapsed:.1f}s"
            )
        text.append(head + "\n", style=f"bold {WARNING_COLOR}")
        if self._expanded and body:
            text.append(body + "\n", style=MUTED_COLOR)
        self.update(text)

    def append(self, chunk: str) -> None:
        self._text += chunk
        self._refresh_content()

    def finish(self) -> float:
        self._elapsed = time.monotonic() - self._start
        self._done = True
        if self._timer is not None:
            self._timer.stop()
        self._refresh_content()
        return self._elapsed

    def replay(self, text: str, elapsed: float, expanded: bool = False) -> None:
        self._text = text
        self._elapsed = elapsed
        self._done = True
        self._expanded = expanded
        self._refresh_content()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._refresh_content()

    def on_click(self) -> None:
        if self._done:
            self._expanded = not self._expanded
            self._refresh_content()


class Spinner(Static):
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def on_mount(self) -> None:
        self._i = 0
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        self._i = (self._i + 1) % len(self.FRAMES)
        self.update(f"[#6b7280]{self.FRAMES[self._i]} thinking…[/]")


class Sidebar(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("", id="side-title")
        yield Static("", id="side-context")
        yield Static("", id="side-tools")
        yield Static("", id="side-lsp")
        yield Static("", id="side-todo")

    def set_title(self, text: str) -> None:
        self.query_one("#side-title", Static).update(text or "new session")

    def set_context(self, tokens: int, percent: float, cost: float) -> None:
        text = Text()
        text.append("Context\n", style="bold #c9d1d9")
        text.append(f"{tokens:,} tokens\n", style="#9ca3af")
        text.append(f"{percent:.0f}% used\n", style="#9ca3af")
        text.append(f"${cost:.2f} spent\n", style="#9ca3af")
        self.query_one("#side-context", Static).update(text)

    def set_tools(self, count: int) -> None:
        text = Text()
        text.append("Tools\n", style="bold #c9d1d9")
        text.append(f"{count} enabled\n", style="#9ca3af")
        self.query_one("#side-tools", Static).update(text)

    def set_lsp(self, message: str) -> None:
        text = Text()
        text.append("LSP\n", style="bold #c9d1d9")
        text.append(f"{message}\n", style="#9ca3af")
        self.query_one("#side-lsp", Static).update(text)

    def set_todos(self, todos: list) -> None:
        text = Text()
        text.append("todo\n", style="bold #c9d1d9")
        if not todos:
            text.append("none\n", style="#6b7280")
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
        self.query_one("#side-todo", Static).update(text)


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
    #main { height: 1fr; }
    #chat { width: 1fr; padding: 0 1; }
    #sidebar { width: 40; border-left: solid $surface; padding: 1 1; }
    Sidebar Static { height: auto; margin: 0 0 1 0; }
    #side-title { text-style: bold; color: $foreground; }
    .meta { color: $text-muted; padding: 0 0 0 3; height: auto; margin: 0 0 1 0; }
    #bottom { dock: bottom; height: auto; }
    #statusbar { height: 1; background: $panel; padding: 0 1; }
    #status-left { width: 1fr; }
    #status-right { width: auto; text-align: right; }
    .msg { margin: 0 0 1 0; padding: 0 0 0 1; height: auto; }
    .msg.you { border-left: thick #5c9cf5; }
    .msg.mybot { border-left: none; }
    .role { height: 1; text-style: bold; color: #808080; }
    .msg.you .role { color: #5c9cf5; }
    .msg.mybot .role { color: #808080; }
    Markdown { color: #eeeeee; link-color: #fab283; link-style: underline; }
    MarkdownH1, MarkdownH2, MarkdownH3, MarkdownH4, MarkdownH5, MarkdownH6 { color: #9d7cd8; text-style: bold; }
    MarkdownBlockQuote { color: #e5c07b; }
    MarkdownBullet { color: #fab283; }
    MarkdownBlock > .em { color: #e5c07b; text-style: italic; }
    MarkdownBlock > .strong { color: #f5a742; text-style: bold; }
    MarkdownBlock > .code_inline { color: #7fd88f; background: #1e1e1e; }
    MarkdownFence { background: #141414; color: #eeeeee; }
    MarkdownTableContent > .markdown-table--header { color: #fab283; text-style: bold; }
    .tool { padding: 0 0 0 3; height: auto; }
    .thinking { margin: 0 0 1 0; padding: 0 0 0 3; height: auto; }
    #prompt { height: auto; max-height: 10; border: none; background: $panel; padding: 0 1; }
    #prompt:focus { border: none; }
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
    #home { height: 1fr; align: center middle; }
    #logo { width: 75; text-align: center; height: auto; }
    #home-prompt { width: 75; height: auto; border-left: thick $secondary; background: $panel; padding: 1 2; }
    #home-input { width: 100%; height: auto; max-height: 10; border: none; background: $panel; color: $foreground; }
    #home-input:focus { border: none; }
    #home-input .text-area--placeholder, #prompt .text-area--placeholder { color: $text-muted; }
    #home-agent { width: 100%; height: 1; margin: 1 0 0 0; }
    #home-hints { width: 100%; height: 1; color: $text-muted; }
    #home-tip { width: 75; text-align: center; color: $text-muted; margin: 3 0 0 0; height: auto; }
    #home-footer { dock: bottom; height: 1; padding: 0 2; }
    #home-dir { width: 1fr; color: $text-muted; }
    #home-version { width: auto; color: $text-muted; }
    Chooser { align: center middle; }
    #palette { width: 60; height: auto; max-height: 80%; border: thick $primary; background: $surface; padding: 1 2; }
    #palette-title { text-style: bold; color: $primary; margin: 0 0 1 0; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "quit"),
        Binding("tab", "mode", "mode"),
        Binding("ctrl+p", "palette", "palette"),
        Binding("ctrl+x", "leader", "leader", show=False),
        Binding("ctrl+t", "theme", "theme"),
        Binding("ctrl+o", "toggle_todos", "sidebar"),
        Binding("ctrl+n", "new", "new"),
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+r", "reset", "reset", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.agent = None
        self.busy = False
        self.mode = "build"
        self.view = "home"
        self.title = "new session"
        self.tokens_in = 0
        self.tokens_out = 0
        self.context_tokens = 0
        self.show_thinking = False
        self.show_details = False
        self._last_tool = None
        self._last_tool_record = None
        self._thinking = None
        self._thinking_views = []
        self._tool_views = []
        self._spinner = None
        self._leader = False
        self._cancel = threading.Event()
        self.sessions = [Session()]
        self.index = 0
        self._undo_stack = []
        self._redo_stack = []

    def _session(self) -> Session:
        return self.sessions[self.index]

    def _record(self, record: dict) -> None:
        self.sessions[self.index].records.append(record)

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield VerticalScroll(id="chat")
            yield Sidebar(id="sidebar")
        with Vertical(id="home"):
            yield Static(_logo(), id="logo")
            with Vertical(id="home-prompt"):
                yield PromptArea(placeholder=_placeholder_text(), id="home-input")
                yield Static("", id="home-agent")
                yield Static(_hint_text(), id="home-hints")
            yield Static(_tip_text(is_configured()), id="home-tip")
        with Vertical(id="bottom"):
            yield PromptArea(placeholder="Ask mybot anything...", id="prompt")
            with Horizontal(id="statusbar"):
                yield Static("", id="status-left")
                yield Static("", id="status-right")
        with Horizontal(id="home-footer"):
            yield Static("", id="home-dir")
            yield Static(VERSION, id="home-version")

    def on_mount(self) -> None:
        self._register_themes()
        self.theme = "opencode"
        set_approval_handler(self._approve)
        if is_configured():
            try:
                self.agent = Agent(system_prompt=self._system_prompt())
            except Exception as exc:
                self._note(f"error: {exc}")
        self.sessions[0].agent = self.agent
        sidebar = self.query_one(Sidebar)
        sidebar.set_title(self.title)
        sidebar.set_tools(len(TOOL_SPECS))
        sidebar.set_lsp("LSPs are disabled")
        sidebar.set_todos(get_todos())
        self._refresh_status()
        self._set_view("home")
        self._refresh_home_meta()
        self._rotate_placeholder()

    def _rotate_placeholder(self) -> None:
        try:
            self.query_one("#home-input", PromptArea).placeholder = _placeholder_text()
        except Exception:
            pass

    def _register_themes(self) -> None:
        self.register_theme(
            Theme(
                "opencode",
                primary="#fab283",
                secondary="#5c9cf5",
                accent="#9d7cd8",
                foreground="#eeeeee",
                background="#0a0a0a",
                surface="#141414",
                panel="#1e1e1e",
                success="#7fd88f",
                warning="#f5a742",
                error="#e06c75",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "catppuccin",
                primary="#cba6f7",
                secondary="#89b4fa",
                accent="#94e2d5",
                background="#1e1e2e",
                surface="#313244",
                panel="#181825",
                success="#a6e3a1",
                warning="#f9e2af",
                error="#f38ba8",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "one-dark",
                primary="#61afef",
                secondary="#c678dd",
                accent="#56b6c2",
                background="#282c34",
                surface="#3a3f4b",
                panel="#21252b",
                success="#98c379",
                warning="#e5c07b",
                error="#e06c75",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                "matrix",
                primary="#00ff41",
                secondary="#00cc33",
                accent="#33ff77",
                background="#0a0f0a",
                surface="#0f1a0f",
                panel="#0a0f0a",
                success="#00ff41",
                warning="#aaff00",
                error="#ff3333",
                dark=True,
            )
        )
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

    def _refresh_status(self) -> None:
        model = self.agent.model if self.agent else "not connected"
        provider = load_auth().get("provider", "")
        left = Text()
        left.append(self.mode.capitalize(), style=f"bold {ACCENT_SOFT}")
        left.append(" auto · ", style="#8b93a7")
        left.append(model, style="#e5e7eb")
        if provider:
            left.append(f" {provider}", style="#6b7280")
        self.query_one("#status-left", Static).update(left)

        cost = self._cost()
        right = Text()
        right.append(f"{WORKSPACE}   ", style="#6b7280")
        if self.context_tokens:
            right.append(
                f"{self.context_tokens:,} ({self._context_percent():.0f}%)   ", style="#6b7280"
            )
        if cost is not None:
            right.append(f"${cost:.4f}   ", style="#6b7280")
        right.append("ctrl+p commands", style="#6b7280")
        self.query_one("#status-right", Static).update(right)

        sidebar = self.query_one(Sidebar)
        sidebar.set_context(self.context_tokens, self._context_percent(), cost or 0.0)

    def _context_percent(self) -> float:
        model = self.agent.model if self.agent else ""
        window = CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT)
        if not window:
            return 0.0
        return min(100.0, self.context_tokens / window * 100)

    def _cost(self):
        model = self.agent.model if self.agent else ""
        price = PRICING.get(model)
        if price is None:
            return None
        return self.tokens_in / 1e6 * price[0] + self.tokens_out / 1e6 * price[1]

    def _set_view(self, view: str) -> None:
        self.view = view
        chat = view == "chat"
        self.query_one("#main").display = chat
        self.query_one("#bottom").display = chat
        self.query_one("#home").display = not chat
        self.query_one("#home-footer").display = not chat
        if chat:
            self.query_one("#prompt", PromptArea).focus()
        else:
            self.query_one("#home-input", PromptArea).focus()

    def _refresh_home_meta(self) -> None:
        meta = Text()
        if self.agent is not None:
            provider = load_auth().get("provider", "")
            meta.append(self.mode.capitalize(), style=f"bold {ACCENT_SOFT}")
            meta.append(" auto ", style=MUTED)
            meta.append("· ", style=MUTED)
            meta.append(self.agent.model, style=TEXT_COLOR)
            if provider:
                meta.append(f"  {provider}", style=MUTED)
        else:
            meta.append("not connected", style=WARNING_COLOR)
            meta.append("   Run ", style=MUTED)
            meta.append("/connect", style=TEXT_COLOR)
            meta.append(" to add an AI provider", style=MUTED)
        self.query_one("#home-agent", Static).update(meta)
        self.query_one("#home-dir", Static).update(str(WORKSPACE))

    def _scroll_end(self) -> None:
        try:
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _note(self, text: str) -> None:
        if self.view == "home":
            self._set_view("chat")
        self.query_one("#chat", VerticalScroll).mount(MessageView("mybot", text))
        self._scroll_end()

    def on_prompt_area_submitted(self, event: PromptArea.Submitted) -> None:
        text = event.value.strip()
        event.area.load_text("")
        if not text or self.busy:
            return
        self._rotate_placeholder()
        if text.startswith("/"):
            self._command(text)
            return
        if self.view == "home":
            self._set_view("chat")
        if self.title == "new session":
            self.title = text[:40]
            self._session().title = self.title
            self.query_one(Sidebar).set_title(self.title)
        self._push_undo()
        self._record({"role": "you", "text": text})
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(MessageView("you", text))
        if text.startswith("!"):
            self._run_bash(text[1:].strip())
            return
        assistant = MessageView("mybot", "")
        chat.mount(assistant)
        self._scroll_end()
        self.busy = True
        self._cancel.clear()
        self._thinking = None
        self._start_spinner()
        self._refresh_status()
        self._run_agent(self._expand_refs(text), assistant)

    def _expand_refs(self, text: str) -> str:
        refs = [token[1:] for token in text.split() if token.startswith("@") and len(token) > 1]
        blocks = []
        for ref in refs:
            content = read_file(ref)
            if not content.startswith("ERROR"):
                blocks.append(f"--- {ref} ---\n{content}")
        return text + "\n\n" + "\n\n".join(blocks) if blocks else text

    def _start_spinner(self) -> None:
        self._stop_spinner()
        self._spinner = Spinner()
        self.query_one("#chat", VerticalScroll).mount(self._spinner)
        self._scroll_end()

    def _stop_spinner(self) -> None:
        if self._spinner is not None:
            try:
                self._spinner.remove()
            except Exception:
                pass
            self._spinner = None

    def _command(self, text: str) -> None:
        command = text.split()[0].lower()
        mapping = {
            "/connect": "connect",
            "/models": "models",
            "/theme": "theme",
            "/themes": "theme",
            "/mode": "mode",
            "/thinking": "thinking",
            "/details": "details",
            "/compact": "compact",
            "/summarize": "compact",
            "/export": "export",
            "/reset": "reset",
            "/help": "help",
            "/new": "new",
            "/clear": "new",
            "/sessions": "sessions",
            "/resume": "sessions",
            "/continue": "sessions",
            "/undo": "undo",
            "/redo": "redo",
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
        elif action == "thinking":
            self._toggle_thinking()
        elif action == "details":
            self._toggle_details()
        elif action == "compact":
            self._compact()
        elif action == "export":
            self._export()
        elif action == "sessions":
            self._sessions_command()
        elif action == "undo":
            self.action_undo()
        elif action == "redo":
            self.action_redo()
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
            self._refresh_status()
            self._refresh_home_meta()
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
            self._refresh_status()
            self._refresh_home_meta()
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
            self._refresh_status()
            self._refresh_home_meta()
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
        start = time.monotonic()
        try:
            for event in self.agent.respond_stream(text):
                if self._cancel.is_set():
                    self.call_from_thread(assistant.append, "\n\n_\\[cancelled]_")
                    break
                kind = event["type"]
                if kind == "reasoning":
                    self.call_from_thread(self._stop_spinner)
                    self.call_from_thread(self._add_reasoning, event["text"])
                elif kind == "delta":
                    self.call_from_thread(self._stop_spinner)
                    self.call_from_thread(assistant.append, event["text"])
                elif kind == "tool":
                    self.call_from_thread(self._stop_spinner)
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
                        self._finalize,
                        assistant,
                        event["text"] or assistant._text,
                        time.monotonic() - start,
                    )
        except Exception as exc:
            self.call_from_thread(assistant.set_text, f"error: {exc}")
        finally:
            self.call_from_thread(self._finish)

    def _finalize(self, assistant: MessageView, text: str, elapsed: float) -> None:
        assistant.set_text(text)
        self._record({"role": "mybot", "text": text})
        meta = Text()
        meta.append("▪ ", style=ACCENT_SOFT)
        meta.append(self.mode.capitalize(), style=ACCENT_SOFT)
        meta.append(" · ", style="#4b5563")
        meta.append(self.agent.model if self.agent else "", style="#9ca3af")
        meta.append(f" · {elapsed:.1f}s", style="#6b7280")
        self.query_one("#chat", VerticalScroll).mount(Static(meta, classes="meta"))
        self._record({"kind": "meta", "text": meta.plain})
        self._scroll_end()

    def _add_usage(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.context_tokens = tokens_in
        self._refresh_status()

    def _add_reasoning(self, chunk: str) -> None:
        if self._thinking is None:
            self._thinking = ThinkingView(expanded=self.show_thinking)
            self._thinking_views.append(self._thinking)
            self.query_one("#chat", VerticalScroll).mount(self._thinking)
        self._thinking.append(chunk)
        self._scroll_end()

    def _add_tool(self, name: str, args: str) -> None:
        view = ToolView(name, args, detailed=self.show_details)
        record = {"kind": "tool", "name": name, "args": args, "result": ""}
        self._record(record)
        self._last_tool = view
        self._last_tool_record = record
        self._tool_views.append(view)
        self.query_one("#chat", VerticalScroll).mount(view)
        self._scroll_end()

    def _tool_result(self, result: str) -> None:
        if self._last_tool is not None:
            self._last_tool.set_result(result)
        if self._last_tool_record is not None:
            self._last_tool_record["result"] = result
        self._scroll_end()

    @work(thread=True)
    def _run_bash(self, command: str) -> None:
        view = ToolView("bash", command)
        self.call_from_thread(self._mount_tool, view)
        result = run_shell(command)
        self.call_from_thread(view.set_result, result)
        self.call_from_thread(self._set_last_tool_result, result)
        self.call_from_thread(self._bash_context, command, result)

    def _set_last_tool_result(self, result: str) -> None:
        if self._last_tool_record is not None:
            self._last_tool_record["result"] = result

    def _mount_tool(self, view: ToolView) -> None:
        record = {"kind": "tool", "name": view.tool_name, "args": view.tool_args, "result": ""}
        self._record(record)
        self._last_tool = view
        self._last_tool_record = record
        self._tool_views.append(view)
        self.query_one("#chat", VerticalScroll).mount(view)
        self._scroll_end()

    def _bash_context(self, command: str, result: str) -> None:
        if self.agent is not None:
            self.agent.messages.append(
                {"role": "user", "content": f"(shell) {command}\n{result}"}
            )
        self._scroll_end()

    def _refresh_todos(self) -> None:
        self.query_one(Sidebar).set_todos(get_todos())

    def _finish(self) -> None:
        self._stop_spinner()
        if self._thinking is not None:
            elapsed = self._thinking.finish()
            self._record(
                {"kind": "thinking", "text": self._thinking._text, "elapsed": elapsed}
            )
            self._thinking = None
        self.busy = False
        self._refresh_status()
        self._scroll_end()
        self.query_one("#prompt", PromptArea).focus()

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

    def _toggle_thinking(self) -> None:
        self.show_thinking = not self.show_thinking
        for view in self._thinking_views:
            view.set_expanded(self.show_thinking)
        self._note(f"Thinking: {'expanded' if self.show_thinking else 'collapsed'}")

    def _toggle_details(self) -> None:
        self.show_details = not self.show_details
        for view in self._tool_views:
            view.set_detailed(self.show_details)
        self._note(f"Tool details: {'expanded' if self.show_details else 'compact'}")

    @work(thread=True)
    def _compact(self) -> None:
        if self.agent is None:
            self.call_from_thread(self._note, "Connect first with /connect.")
            return
        try:
            summary = self.agent.compact()
        except Exception as exc:
            self.call_from_thread(self._note, f"compact error: {exc}")
            return
        self.call_from_thread(self._note, f"Compacted into a summary.\n\n{summary}")

    def _export(self) -> None:
        parts = []
        for child in self.query_one("#chat", VerticalScroll).children:
            if isinstance(child, MessageView):
                parts.append(f"## {child.role_name}\n\n{child._text}\n")
            elif isinstance(child, ToolView):
                parts.append(f"> tool `{child.tool_name}`: {child.tool_args}\n")
        try:
            out = WORKSPACE / f"mybot-export-{int(time.time())}.md"
            out.write_text("\n".join(parts), encoding="utf-8")
        except Exception as exc:
            self._note(f"export error: {exc}")
            return
        self._note(f"Exported conversation to {out}")

    def action_leader(self) -> None:
        self._leader = True
        self._note(
            "leader: n new · l sessions · u undo · r redo · t theme · m models · c compact · x export · q quit"
        )

    def on_key(self, event) -> None:
        if not getattr(self, "_leader", False):
            return
        self._leader = False
        event.stop()
        action = {
            "n": "new",
            "q": "quit",
            "t": "theme",
            "m": "models",
            "c": "compact",
            "x": "export",
            "l": "sessions",
            "u": "undo",
            "r": "redo",
        }.get(event.key)
        if action:
            self._run_command(action)

    def _push_undo(self) -> None:
        if self.agent is None:
            return
        self._undo_stack.append((len(self.agent.messages), len(self._session().records)))
        self._redo_stack.clear()

    def action_undo(self) -> None:
        if self.busy:
            self._note("Busy.")
            return
        if self.agent is None or not self._undo_stack:
            self._note("Nothing to undo.")
            return
        msg_len, rec_len = self._undo_stack.pop()
        removed_msgs = self.agent.messages[msg_len:]
        removed_recs = self._session().records[rec_len:]
        del self.agent.messages[msg_len:]
        del self._session().records[rec_len:]
        self._redo_stack.append((msg_len, rec_len, removed_msgs, removed_recs))
        self._rebuild_chat()
        self._refresh_status()
        self._note("Undid last turn.")

    def action_redo(self) -> None:
        if self.busy:
            self._note("Busy.")
            return
        if self.agent is None or not self._redo_stack:
            self._note("Nothing to redo.")
            return
        msg_len, rec_len, removed_msgs, removed_recs = self._redo_stack.pop()
        self.agent.messages[msg_len:msg_len] = removed_msgs
        self._session().records[rec_len:rec_len] = removed_recs
        self._undo_stack.append((msg_len, rec_len))
        self._rebuild_chat()
        self._refresh_status()
        self._note("Redid last turn.")

    def _rebuild_chat(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        self._thinking_views = []
        self._tool_views = []
        self._thinking = None
        for record in self._session().records:
            if "role" in record:
                chat.mount(MessageView(record["role"], record["text"]))
            elif record["kind"] == "thinking":
                view = ThinkingView(expanded=self.show_thinking)
                view.replay(
                    record["text"], record.get("elapsed", 0.0), expanded=self.show_thinking
                )
                self._thinking_views.append(view)
                chat.mount(view)
            elif record["kind"] == "tool":
                view = ToolView(record["name"], record["args"], detailed=self.show_details)
                view.set_result(record["result"])
                self._tool_views.append(view)
                chat.mount(view)
            elif record["kind"] == "meta":
                chat.mount(Static(record["text"], classes="meta"))
        self._scroll_end()

    def _sessions_command(self) -> None:
        options = [
            (f"{i + 1}. {session.title}", str(i)) for i, session in enumerate(self.sessions)
        ]

        def done(choice) -> None:
            if choice is not None:
                self._select_session(int(choice))

        self.push_screen(Chooser("sessions", options), done)

    def _select_session(self, index: int) -> None:
        current = self._session()
        current.tokens_in = self.tokens_in
        current.tokens_out = self.tokens_out
        current.context_tokens = self.context_tokens
        self.index = index
        session = self._session()
        self.agent = session.agent
        self.title = session.title
        self.tokens_in = session.tokens_in
        self.tokens_out = session.tokens_out
        self.context_tokens = session.context_tokens
        self.query_one(Sidebar).set_title(self.title)
        self._rebuild_chat()
        self._set_view("chat" if session.records else "home")
        self._refresh_status()

    def action_reset(self) -> None:
        if self.agent is not None:
            self.agent.reset()
        self._note("History cleared.")

    def action_new(self) -> None:
        if self.busy:
            self._note("Busy.")
            return
        agent = None
        if is_configured():
            try:
                agent = Agent(system_prompt=self._system_prompt())
            except Exception as exc:
                self._note(f"error: {exc}")
        self.sessions.append(Session(agent))
        self._undo_stack = []
        self._redo_stack = []
        self._select_session(len(self.sessions) - 1)
        todo_write([])
        self.query_one(Sidebar).set_todos([])
        self._refresh_home_meta()
        self._rotate_placeholder()

    def action_toggle_todos(self) -> None:
        sidebar = self.query_one(Sidebar)
        sidebar.display = not sidebar.display

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
