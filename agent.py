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
        self.messages = [{"role": "system", "content": system_prompt}]

    def reset(self) -> None:
        self.messages = [self.messages[0]]

    def _trim(self) -> None:
        user_indices = [i for i, msg in enumerate(self.messages) if msg.get("role") == "user"]
        if len(user_indices) > self.history_limit:
            cut = user_indices[len(user_indices) - self.history_limit]
            self.messages = [self.messages[0]] + self.messages[cut:]

    def respond(self, user_text: str, on_event=None) -> str:
        def emit(event):
            if on_event:
                on_event(event)

        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOL_SPECS,
                tool_choice="auto",
            )
            message = completion.choices[0].message
            self.messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                self._trim()
                return message.content or ""

            for call in message.tool_calls:
                emit({"type": "tool", "name": call.function.name, "args": call.function.arguments})
                result = execute_tool(call.function.name, call.function.arguments)
                emit({"type": "tool_result", "name": call.function.name, "result": result})
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        self._trim()
        return "Stopped: reached the tool-call limit for one turn."
