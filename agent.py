from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, SYSTEM_PROMPT
from tools import TOOL_SPECS, execute_tool

MAX_TOOL_ROUNDS = 12


class Agent:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT, history_limit: int = 40):
        if not LLM_API_KEY:
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self.client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        self.history_limit = history_limit
        self.messages = [{"role": "system", "content": system_prompt}]

    def reset(self) -> None:
        self.messages = [self.messages[0]]

    def _trim(self) -> None:
        if len(self.messages) > self.history_limit:
            self.messages = [self.messages[0]] + self.messages[-self.history_limit :]

    def respond(self, user_text: str, on_event=None) -> str:
        def emit(event):
            if on_event:
                on_event(event)

        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            completion = self.client.chat.completions.create(
                model=LLM_MODEL,
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
