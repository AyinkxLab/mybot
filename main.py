import sys

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
from tools import set_approval_handler


def _approve(action: str) -> bool:
    try:
        reply = input(f"\n[approval] {action}\nallow? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return reply in {"y", "yes"}


set_approval_handler(_approve)


def _connect() -> bool:
    names = list(PROVIDERS)
    print("providers: " + ", ".join(names))
    pre_key = ""
    raw = input("provider (Enter for deepseek, or paste your key): ").strip()
    if not raw or raw.lower() in PROVIDERS:
        provider = raw.lower() or "deepseek"
    elif looks_like_api_key(raw):
        provider = "deepseek"
        pre_key = raw
        print(f"that looks like a key - using provider {provider}")
    else:
        provider = raw.lower()
        while provider not in PROVIDERS:
            print(f"unknown provider '{provider}'. pick one of: {', '.join(names)}")
            provider = input("provider (Enter for deepseek): ").strip().lower() or "deepseek"
    preset = PROVIDERS[provider]
    base_url = preset.get("base_url", "") or input("base URL: ").strip()

    api_key = pre_key or input("API key: ").strip()
    if not api_key:
        print("no key entered, cancelled")
        return False

    print("asking the provider for available models...")
    models = list_models(base_url, api_key)
    if not models:
        print("(could not reach the provider; showing known defaults)")
        models = preset.get("models", [])

    if models:
        for index, name in enumerate(models, 1):
            print(f"  {index}) {name}")
        choice = input(f"model [1]: ").strip() or "1"
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            model = models[int(choice) - 1]
        else:
            model = choice
    else:
        model = input("model: ").strip()

    save_auth(
        {"provider": provider, "base_url": base_url, "api_key": api_key, "model": model}
    )
    print(f"connected: {provider} / {model}")
    print(f"saved to {AUTH_PATH} - reused automatically next time")
    return True


def _change_model() -> bool:
    auth = load_auth()
    if not auth.get("api_key"):
        print("connect first with /connect")
        return False
    print("asking the provider for available models...")
    models = list_models(auth.get("base_url", ""), auth["api_key"])
    if not models:
        models = PROVIDERS.get(auth.get("provider", ""), {}).get("models", [])
    if not models:
        print("no models found")
        return False
    current = auth.get("model", "")
    for index, name in enumerate(models, 1):
        mark = "  (current)" if name == current else ""
        print(f"  {index}) {name}{mark}")
    choice = input("model number or name: ").strip()
    if not choice:
        return False
    if choice.isdigit() and 1 <= int(choice) <= len(models):
        model = models[int(choice) - 1]
    else:
        model = choice
    auth["model"] = model
    save_auth(auth)
    print(f"model set to {model}")
    return True


def _print_event(event: dict) -> None:
    if event["type"] == "tool":
        print(f"  [tool] {event['name']}({event['args']})", file=sys.stderr)
    elif event["type"] == "tool_result":
        preview = event["result"].replace("\n", " ")[:160]
        print(f"  [result] {preview}", file=sys.stderr)


def main() -> None:
    print("mybot ready. Commands: /connect, /models, /reset, /exit")
    agent = None
    if is_configured():
        try:
            agent = Agent()
            print(f"model: {agent.model}")
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
    else:
        print("not connected yet - run /connect to enter your API key.")

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
        if text == "/connect":
            if _connect():
                try:
                    agent = Agent()
                except Exception as exc:
                    print(f"error: {exc}", file=sys.stderr)
            continue
        if text == "/models":
            if _change_model():
                try:
                    agent = Agent()
                except Exception as exc:
                    print(f"error: {exc}", file=sys.stderr)
            continue
        if text == "/reset" and agent is not None:
            agent.reset()
            print("history cleared")
            continue
        if agent is None:
            print("not connected. Run /connect first.", file=sys.stderr)
            continue
        try:
            answer = agent.respond(text, on_event=_print_event)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        print(f"\nbot> {answer}")


if __name__ == "__main__":
    main()
