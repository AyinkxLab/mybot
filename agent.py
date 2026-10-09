import json
from itertools import chain

from openai import OpenAI

from auth import list_models, load_auth
from config import (
    CORE_TOOLS,
    ESCALATE_COMPLEX,
    ESCALATE_KEYWORDS,
    HISTORY_LIMIT,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_FALLBACK_API_KEY,
    LLM_FALLBACK_BASE_URL,
    LLM_FALLBACK_MODEL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
    TOOLSET_MODE,
)
from tools import all_tool_specs, execute_tool

# When a request contains one of these, we override the default "minimum work"
# behaviour and tell the model to be exhaustive for that turn.
THOROUGH_HINTS = (
    "don't skip",
    "dont skip",
    "do not skip",
    "be thorough",
    "thoroughly",
    "exhaustive",
    "check everything",
    "cover all",
    "no shortcuts",
    "leave nothing",
    "full audit",
    "everything relevant",
    "deep dive",
)

_THOROUGH_NUDGE = (
    "\n\n[Be exhaustive for this task: check everything relevant, don't skip any step, "
    "and verify thoroughly.]"
)


class Agent:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT, history_limit: int = HISTORY_LIMIT):
        auth = load_auth()
        api_key = auth.get("api_key") or LLM_API_KEY
        self.base_url = auth.get("base_url") or LLM_BASE_URL
        self.model = auth.get("model") or LLM_MODEL
        if not api_key:
            raise RuntimeError("No API key set. Run /connect to add your provider key.")
        self.client = OpenAI(api_key=api_key, base_url=self.base_url)
        self.fallback_client = None
        self.fallback_model = LLM_FALLBACK_MODEL or None
        self._fallback_checked = False
        self.history_limit = history_limit
        try:
            from memory import format_notes

            notes = format_notes()
            if notes and not notes.startswith("("):
                system_prompt = system_prompt + "\n\nThings you remember:\n" + notes
        except Exception:
            pass
        self.messages = [{"role": "system", "content": system_prompt}]

    def reset(self) -> None:
        self.messages = [self.messages[0]]

    def compact(self) -> str:
        request = self.messages + [
            {
                "role": "user",
                "content": "Summarize our conversation so far in one concise paragraph, keeping "
                "key facts, decisions, and unfinished tasks.",
            }
        ]
        response = self.client.chat.completions.create(model=self.model, messages=request)
        summary = response.choices[0].message.content or ""
        self.messages = [
            {
                "role": "system",
                "content": self.messages[0]["content"]
                + "\n\nSummary of the earlier conversation:\n"
                + summary,
            }
        ]
        return summary

    def _trim(self) -> None:
        user_indices = [i for i, msg in enumerate(self.messages) if msg.get("role") == "user"]
        if len(user_indices) > self.history_limit:
            cut = user_indices[len(user_indices) - self.history_limit]
            self.messages = [self.messages[0]] + self.messages[cut:]

    def respond(self, user_text: str, on_event=None) -> str:
        final = ""
        for event in self.respond_stream(user_text):
            if on_event is not None:
                on_event(event)
            if event["type"] == "final":
                final = event["text"]
        return final

    def _fallback(self):
        if self.fallback_client is not None or self._fallback_checked:
            return self.fallback_client, self.fallback_model
        self._fallback_checked = True
        try:
            model = self.fallback_model
            if not model:
                models = list_models(LLM_FALLBACK_BASE_URL, LLM_FALLBACK_API_KEY)
                model = models[0] if models else None
            if model:
                self.fallback_client = OpenAI(
                    api_key=LLM_FALLBACK_API_KEY, base_url=LLM_FALLBACK_BASE_URL
                )
                self.fallback_model = model
        except Exception:
            pass
        return self.fallback_client, self.fallback_model

    def _open_stream(self, client, model):
        tools = all_tool_specs()
        if TOOLSET_MODE == "core":
            tools = [spec for spec in tools if spec["function"]["name"] in CORE_TOOLS]
        request = {
            "model": model,
            "messages": self.messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        if LLM_MAX_TOKENS > 0:
            request["max_tokens"] = LLM_MAX_TOKENS
        try:
            return client.chat.completions.create(
                **request, stream_options={"include_usage": True}
            )
        except Exception:
            return client.chat.completions.create(**request)

    def _should_escalate(self, text: str) -> bool:
        if not ESCALATE_COMPLEX:
            return False
        if len(text) > 700 or "```" in text:
            return True
        lowered = text.lower()
        return any(keyword in lowered for keyword in ESCALATE_KEYWORDS)

    def respond_stream(self, user_text: str, model: str = None, images: list = None):
        if any(hint in user_text.lower() for hint in THOROUGH_HINTS):
            user_text = user_text + _THOROUGH_NUDGE
        content = user_text
        if images:
            content = [{"type": "text", "text": user_text}]
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": image}})
        self.messages.append({"role": "user", "content": content})
        turn_start = len(self.messages)

        primary = (self.client, model or self.model)
        fb_client, fb_model = self._fallback()
        backup = (fb_client, fb_model) if fb_client is not None else None

        if model is not None or backup is None:
            routes = [primary]
        elif self._should_escalate(user_text):
            routes = [backup, primary]
        else:
            routes = [primary, backup]

        for index, (active_client, active_model) in enumerate(routes):
            try:
                yield from self._run_turn(active_client, active_model)
                return
            except Exception as exc:
                if index == len(routes) - 1:
                    raise
                del self.messages[turn_start:]
                nxt = routes[index + 1][1]
                yield {
                    "type": "notice",
                    "text": f"{active_model} failed ({type(exc).__name__}); escalating to {nxt}",
                }

    def _run_turn(self, active_client, active_model):
        for _ in range(MAX_TOOL_ROUNDS):
            content_parts = []
            tool_calls = {}
            try:
                iterator = iter(self._open_stream(active_client, active_model))
                head = [next(iterator)]
            except StopIteration:
                head = []
                iterator = iter(())
            for chunk in chain(head, iterator):
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    yield {
                        "type": "usage",
                        "input": getattr(usage, "prompt_tokens", 0) or 0,
                        "output": getattr(usage, "completion_tokens", 0) or 0,
                    }
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None) or getattr(
                    delta, "reasoning", None
                )
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}
                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "delta", "text": delta.content}
                if delta.tool_calls:
                    for call in delta.tool_calls:
                        entry = tool_calls.setdefault(
                            call.index, {"id": "", "name": "", "arguments": ""}
                        )
                        if call.id:
                            entry["id"] = call.id
                        if call.function:
                            if call.function.name:
                                entry["name"] += call.function.name
                            if call.function.arguments:
                                entry["arguments"] += call.function.arguments

            content = "".join(content_parts)
            assistant = {"role": "assistant", "content": content or None}
            if tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": entry["id"],
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": entry["arguments"]},
                    }
                    for _, entry in sorted(tool_calls.items())
                ]
            self.messages.append(assistant)

            if not tool_calls:
                self._trim()
                yield {"type": "final", "text": content}
                return

            for call in assistant["tool_calls"]:
                name = call["function"]["name"]
                yield {"type": "tool", "name": name, "args": call["function"]["arguments"]}
                result = execute_tool(name, call["function"]["arguments"])
                image = None
                if name == "take_screenshot":
                    try:
                        parsed = json.loads(result)
                        if isinstance(parsed, dict) and parsed.get("type") == "image":
                            image = parsed
                    except (json.JSONDecodeError, TypeError):
                        image = None
                if image:
                    label = f"screenshot {image.get('width')}x{image.get('height')} (attached)"
                    yield {"type": "tool_result", "name": name, "result": label}
                    self.messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": label}
                    )
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Current screen:"},
                                {"type": "image_url", "image_url": {"url": image["data_url"]}},
                            ],
                        }
                    )
                else:
                    yield {"type": "tool_result", "name": name, "result": result}
                    self.messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": result}
                    )

        self._trim()
        yield {
            "type": "final",
            "text": f"Stopped after {MAX_TOOL_ROUNDS} tool rounds. Raise MAX_TOOL_ROUNDS to run longer.",
        }
