import sys

from agent import Agent
from tools import set_approval_handler


def _approve(action: str) -> bool:
    try:
        reply = input(f"\n[approval] {action}\nallow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return reply in {"y", "yes"}


set_approval_handler(_approve)


def _print_event(event: dict) -> None:
    if event["type"] == "tool":
        print(f"  [tool] {event['name']}({event['args']})", file=sys.stderr)
    elif event["type"] == "tool_result":
        preview = event["result"].replace("\n", " ")[:160]
        print(f"  [result] {preview}", file=sys.stderr)


def main() -> None:
    print("mybot ready. Commands: /reset, /exit")
    agent = Agent()
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            break
        if text == "/reset":
            agent.reset()
            print("history cleared")
            continue
        try:
            answer = agent.respond(text, on_event=_print_event)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        print(f"\nbot> {answer}")


if __name__ == "__main__":
    main()
