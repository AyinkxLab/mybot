"""Read and write the Windows clipboard."""


def register(api):
    import subprocess

    def clipboard_read():
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            return f"ERROR: {exc}"
        return result.stdout.strip() or "(clipboard is empty)"

    def clipboard_write(text):
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
                input=str(text),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            return f"ERROR: {exc}"
        return "Copied to clipboard."

    api.register_tool(
        "clipboard_read",
        clipboard_read,
        "Return the current clipboard text.",
        {"type": "object", "properties": {}, "required": []},
    )
    api.register_tool(
        "clipboard_write",
        clipboard_write,
        "Copy text to the clipboard.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
