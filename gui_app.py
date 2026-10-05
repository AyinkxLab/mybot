import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from agent import Agent
from config import LLM_MODEL
from tools import set_approval_handler


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.agent = None
        self.busy = False

        root.title("mybot")
        root.geometry("780x580")

        self.output = scrolledtext.ScrolledText(root, wrap="word", state="disabled")
        self.output.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        frame = tk.Frame(root)
        frame.pack(fill="x", padx=8, pady=8)
        self.entry = tk.Entry(frame)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _event: self.send())
        tk.Button(frame, text="Send", command=self.send).pack(side="left", padx=(6, 0))

        set_approval_handler(self.approve)
        self.log(f"mybot ready (model: {LLM_MODEL}). Type a task, /reset to clear history.\n")

    def log(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def approve(self, action: str) -> bool:
        event = threading.Event()
        result = {}

        def ask() -> None:
            result["ok"] = messagebox.askyesno("Approval needed", action)
            event.set()

        self.root.after(0, ask)
        event.wait()
        return bool(result.get("ok", False))

    def send(self) -> None:
        if self.busy:
            return
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        if text in {"/exit", "/quit"}:
            self.root.destroy()
            return
        if text == "/reset" and self.agent is not None:
            self.agent.reset()
            self.log("history cleared")
            return
        self.log(f"you> {text}")
        self.busy = True
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        try:
            if self.agent is None:
                self.agent = Agent()
            answer = self.agent.respond(text, on_event=self._event)
        except Exception as exc:
            answer = f"error: {exc}"
        self.root.after(0, self.log, f"\nbot> {answer}\n")
        self.root.after(0, self._done)

    def _event(self, event: dict) -> None:
        if event["type"] == "tool":
            self.root.after(0, self.log, f"  [tool] {event['name']}")
        elif event["type"] == "tool_result":
            preview = event["result"].replace("\n", " ")[:120]
            self.root.after(0, self.log, f"  [result] {preview}")

    def _done(self) -> None:
        self.busy = False


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
