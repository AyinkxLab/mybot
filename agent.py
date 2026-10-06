from openai import OpenAI

from auth import load_auth
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, SYSTEM_PROMPT
from tools import TOOL_SPECS, execute_tool

MAX_TOOL_ROUNDS = 12


class Agent:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT, history_limit: int = 40):
        auth = load_auth()
        api_key = auth.get("api_key") or LLM_API_KEY
        self.base_url = auth.get("base_url") or LLM_BASE_URL
        self.model = auth.get("model") or LLM_MODEL
        if not api_key:
            raise RuntimeError("No API key set. Run /connect to add your provider key.")
        self.client = OpenAI(api_key=api_key, base_url=self.base_url)
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

    def respond_stream(self, user_text: str):
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            content_parts = []
            tool_calls = {}
            request = {
                "model": self.model,
                "messages": self.messages,
                "tools": TOOL_SPECS,
                "tool_choice": "auto",
                "stream": True,
            }
            try:
                stream = self.client.chat.completions.create(
                    **request, stream_options={"include_usage": True}
                )
            except Exception:
                stream = self.client.chat.completions.create(**request)
            for chunk in stream:
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
                yield {"type": "tool_result", "name": name, "result": result}
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

        self._trim()
        yield {"type": "final", "text": "Stopped: reached the tool-call limit for one turn."}
