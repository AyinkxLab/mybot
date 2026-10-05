import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from agent import Agent
from auth import PROVIDERS, is_configured, list_models, save_auth
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
        tk.Button(frame, text="Connect", command=self.connect_dialog).pack(side="left", padx=(6, 0))

        set_approval_handler(self.approve)

        if is_configured():
            self._ensure_agent()
        else:
            self.log("not connected. Click Connect to enter your API key.\n")

    def _ensure_agent(self) -> bool:
        if self.agent is not None:
            return True
        try:
            self.agent = Agent()
            self.log(f"connected (model: {self.agent.model}). Type a task, /reset to clear.\n")
            return True
        except Exception as exc:
            self.log(f"not connected: {exc}")
            return False

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

    def connect_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Connect provider")
        dialog.geometry("420x260")
        dialog.grab_set()

        names = list(PROVIDERS)
        tk.Label(dialog, text="Provider").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        provider_box = ttk.Combobox(dialog, values=names, state="readonly")
        provider_box.set("deepseek")
        provider_box.grid(row=0, column=1, sticky="ew", padx=10, pady=6)

        tk.Label(dialog, text="API key").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        key_entry = tk.Entry(dialog, show="*")
        key_entry.grid(row=1, column=1, sticky="ew", padx=10, pady=6)

        tk.Label(dialog, text="Version / model").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        model_box = ttk.Combobox(dialog, values=PROVIDERS["deepseek"]["models"])
        model_box.set(PROVIDERS["deepseek"]["models"][0])
        model_box.grid(row=2, column=1, sticky="ew", padx=10, pady=6)

        tk.Label(dialog, text="Base URL").grid(row=3, column=0, sticky="w", padx=10, pady=6)
        url_entry = tk.Entry(dialog)
        url_entry.insert(0, PROVIDERS["deepseek"]["base_url"])
        url_entry.grid(row=3, column=1, sticky="ew", padx=10, pady=6)

        dialog.columnconfigure(1, weight=1)

        def fetch_models() -> None:
            key = key_entry.get().strip()
            url = url_entry.get().strip()
            if not key or not url:
                messagebox.showwarning("mybot", "Enter API key and base URL first.", parent=dialog)
                return
            fetched = list_models(url, key)
            if fetched:
                model_box.configure(values=fetched)
                model_box.set(fetched[0])
            else:
                messagebox.showinfo("mybot", "Could not fetch models; keeping defaults.", parent=dialog)

        tk.Button(dialog, text="Fetch", command=fetch_models).grid(row=2, column=2, padx=(4, 10))

        def on_provider(_event=None) -> None:
            preset = PROVIDERS.get(provider_box.get(), {})
            models = preset.get("models", [])
            model_box.configure(values=models)
            if models:
                model_box.set(models[0])
            url_entry.delete(0, "end")
            url_entry.insert(0, preset.get("base_url", ""))

        provider_box.bind("<<ComboboxSelected>>", on_provider)

        def save() -> None:
            api_key = key_entry.get().strip()
            if not api_key:
                messagebox.showwarning("mybot", "Enter an API key.", parent=dialog)
                return
            save_auth(
                {
                    "provider": provider_box.get(),
                    "base_url": url_entry.get().strip(),
                    "api_key": api_key,
                    "model": model_box.get().strip(),
                }
            )
            self.agent = None
            dialog.destroy()
            self._ensure_agent()

        tk.Button(dialog, text="Save", command=save).grid(row=4, column=1, sticky="e", padx=10, pady=12)

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
        if text == "/connect":
            self.connect_dialog()
            return
        if text == "/reset" and self.agent is not None:
            self.agent.reset()
            self.log("history cleared")
            return
        if not self._ensure_agent():
            return
        self.log(f"you> {text}")
        self.busy = True
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        try:
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
