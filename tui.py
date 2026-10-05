import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text

from agent import Agent
from auth import (
    AUTH_PATH,
    PROVIDERS,
    is_configured,
    list_models,
    load_auth,
    looks_like_api_key,
    save_auth,
)
from config import REQUIRE_APPROVAL, WORKSPACE
from tools import set_approval_handler


def _setup_console() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding


UNICODE = _setup_console()
PROMPT_CHAR = "❯ " if UNICODE else "> "
TOOL_CHAR = "⚙" if UNICODE else "*"
RESULT_CHAR = "↳" if UNICODE else "->"
DOT = "·" if UNICODE else "-"
ELLIPSIS = "…" if UNICODE else "..."

console = Console(highlight=False)

BANNER = [
    "███╗   ███╗██╗   ██╗██████╗  ██████╗ ████████╗",
    "████╗ ████║╚██╗ ██╔╝██╔══██╗██╔═══██╗╚══██╔══╝",
    "██╔████╔██║ ╚████╔╝ ██████╔╝██║   ██║   ██║   ",
    "██║╚██╔╝██║  ╚██╔╝  ██╔══██╗██║   ██║   ██║   ",
    "██║ ╚═╝ ██║   ██║   ██████╔╝╚██████╔╝   ██║   ",
    "╚═╝     ╚═╝   ╚═╝   ╚═════╝  ╚═════╝    ╚═╝   ",
]
ASCII_BANNER = [
    " __  __ _  _ ___  ___ _____ ",
    "|  \\/  | || | _ )/ _ \\_   _|",
    "| |\\/| | || | _ \\ (_) || |  ",
    "|_|  |_|\\_, |___/\\___/ |_|  ",
    "        |__/                ",
]
BANNER_COLORS = ["#22d3ee", "#38bdf8", "#60a5fa", "#818cf8", "#a78bfa", "#c084fc"]

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
        "bottom-toolbar": "bg:#161622 #8b93b0",
    }
)


def show_banner() -> None:
    console.print()
    lines = BANNER if UNICODE else ASCII_BANNER
    for index, line in enumerate(lines):
        console.print(Text(line, style=f"bold {BANNER_COLORS[index % len(BANNER_COLORS)]}"))
    console.print(
        Text("  local AI assistant", style="italic #6b7280"),
        Text(f"  {DOT}  /connect /models /reset /exit", style="#6b7280"),
    )
    console.print(Rule(style="#1f2937"))


def user_panel(text: str) -> Panel:
    return Panel(
        Text(text, style="bold white"),
        title="[bold green]you[/]",
        title_align="right",
        border_style="#22c55e",
        padding=(0, 1),
    )


def assistant_panel(text: str) -> Panel:
    body = Markdown(text, code_theme="monokai") if text.strip() else Text(ELLIPSIS, style="dim")
    return Panel(
        body,
        title="[bold magenta]mybot[/]",
        title_align="left",
        border_style="#818cf8",
        padding=(0, 1),
    )


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + ELLIPSIS


class StreamView:
    def __init__(self) -> None:
        self.live = None
        self.buffer = ""

    def _start(self) -> None:
        if self.live is None:
            self.live = Live(
                Spinner("dots", text="[dim]thinking...[/]"),
                console=console,
                refresh_per_second=15,
                vertical_overflow="visible",
            )
            self.live.start()

    def _stop(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None

    def handle(self, event: dict) -> None:
        kind = event["type"]
        if kind == "delta":
            self._start()
            self.buffer += event["text"]
            self.live.update(assistant_panel(self.buffer))
        elif kind == "tool":
            self._stop()
            if self.buffer:
                console.print(assistant_panel(self.buffer))
                self.buffer = ""
            console.print(
                f"[bold yellow]{TOOL_CHAR} {event['name']}[/] [dim]{_short(event['args'])}[/]"
            )
        elif kind == "tool_result":
            console.print(f"  [dim]{RESULT_CHAR} {_short(event['result'], 160)}[/]")
        elif kind == "final":
            self._stop()
            text = event["text"] or self.buffer
            if text:
                console.print(assistant_panel(text))
            self.buffer = ""

    def close(self) -> None:
        self._stop()


def _approve(action: str) -> bool:
    console.print(
        Panel(
            Text(action, style="yellow"),
            title="[bold yellow]approval needed[/]",
            border_style="yellow",
            padding=(0, 1),
        )
    )
    try:
        return Confirm.ask("[yellow]allow?[/]", default=False)
    except (EOFError, KeyboardInterrupt):
        return False


set_approval_handler(_approve)


def _connect() -> bool:
    names = list(PROVIDERS)
    for index, name in enumerate(names, 1):
        console.print(f"  [cyan]{index}[/]) {name}")

    pre_key = ""
    raw = Prompt.ask("provider (or paste your API key)", default="deepseek").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(names):
        provider = names[int(raw) - 1]
    elif raw.lower() in PROVIDERS:
        provider = raw.lower()
    elif looks_like_api_key(raw):
        provider = "deepseek"
        pre_key = raw
        console.print(f"[yellow]that looks like a key - using provider[/] [bold]{provider}[/]")
    else:
        provider = raw.lower()
        while provider not in PROVIDERS:
            console.print(f"[red]unknown provider:[/] {provider}")
            provider = Prompt.ask("provider", default="deepseek").strip().lower()

    preset = PROVIDERS[provider]
    base_url = Prompt.ask("base URL", default=preset.get("base_url", ""))
    api_key = pre_key or Prompt.ask("API key", password=True).strip()
    if not api_key:
        console.print("[red]no key entered, nothing saved[/]")
        return False

    console.print("[dim]asking the provider for available models...[/]")
    models = list_models(base_url, api_key) or preset.get("models", [])
    if not models:
        model = Prompt.ask("model").strip()
    else:
        for index, name in enumerate(models, 1):
            console.print(f"  [cyan]{index}[/]) {name}")
        pick = Prompt.ask("model", default="1").strip()
        if pick.isdigit() and 1 <= int(pick) <= len(models):
            model = models[int(pick) - 1]
        else:
            model = pick

    save_auth({"provider": provider, "base_url": base_url, "api_key": api_key, "model": model})
    console.print(f"[green]saved[/] {provider} / [bold]{model}[/]")
    console.print(f"[dim]stored in {AUTH_PATH} - reused automatically next time[/]\n")
    return True


def _change_model() -> bool:
    auth = load_auth()
    if not auth.get("api_key"):
        console.print("[yellow]connect first with /connect[/]")
        return False
    console.print("[dim]asking the provider for available models...[/]")
    models = list_models(auth.get("base_url", ""), auth["api_key"])
    if not models:
        models = PROVIDERS.get(auth.get("provider", ""), {}).get("models", [])
    if not models:
        console.print("[red]no models found[/]")
        return False
    current = auth.get("model", "")
    for index, name in enumerate(models, 1):
        mark = "  [green](current)[/]" if name == current else ""
        console.print(f"  [cyan]{index}[/]) {name}{mark}")
    pick = Prompt.ask("model", default=current or "1").strip()
    if pick.isdigit() and 1 <= int(pick) <= len(models):
        model = models[int(pick) - 1]
    else:
        model = pick
    auth["model"] = model
    save_auth(auth)
    console.print(f"[green]model set to[/] [bold]{model}[/]\n")
    return True


HELP = """[bold]commands[/]
  [cyan]/connect[/]  set provider, key and model
  [cyan]/models[/]   switch the model
  [cyan]/reset[/]    clear conversation history
  [cyan]/exit[/]     quit
Type any task and press Enter. Tools show as tool lines."""


def _make_agent():
    if not is_configured():
        return None
    try:
        return Agent()
    except Exception as exc:
        console.print(f"[red]{exc}[/]")
        return None


def main() -> None:
    console.clear()
    show_banner()

    agent = _make_agent()
    if agent is None:
        console.print("[yellow]not connected[/] - run [bold]/connect[/] to add your API key.\n")
    else:
        console.print(f"[dim]model[/] [bold]{agent.model}[/]  [dim]{DOT} workspace[/] {WORKSPACE}\n")

    session = PromptSession(style=PROMPT_STYLE)

    def toolbar():
        model = agent.model if agent else "not connected"
        approvals = "on" if REQUIRE_APPROVAL else "off"
        return [
            (
                "class:bottom-toolbar",
                f" {model}  {DOT}  workspace: {WORKSPACE}  {DOT}  approvals: {approvals}  {DOT}  /help ",
            )
        ]

    while True:
        try:
            text = session.prompt([("class:prompt", PROMPT_CHAR)], bottom_toolbar=toolbar).strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break
        if text == "/help":
            console.print(Panel(HELP, border_style="#374151", padding=(0, 1)))
            continue
        if text == "/connect":
            if _connect():
                agent = _make_agent()
            continue
        if text == "/models":
            if _change_model():
                agent = _make_agent()
            continue
        if text == "/reset":
            if agent is not None:
                agent.reset()
                console.print("[dim]history cleared[/]")
            continue

        console.print(user_panel(text))
        if agent is None:
            console.print("[red]not connected[/] - run [bold]/connect[/] first.\n")
            continue

        view = StreamView()
        try:
            view._start()
            for event in agent.respond_stream(text):
                view.handle(event)
        except KeyboardInterrupt:
            console.print("\n[yellow]cancelled[/]")
        except Exception as exc:
            console.print(f"[red]error:[/] {exc}")
        finally:
            view.close()
        console.print()

    console.print("[dim]bye[/]")


if __name__ == "__main__":
    main()
