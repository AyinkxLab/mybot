"""Example mybot plugin.

Drop ``*.py`` files like this into the ``plugins/`` folder. Each file may define a
``register(api)`` function to add tools, slash commands, and event hooks.
"""


def register(api):
    def now():
        import datetime

        return datetime.datetime.now().isoformat(timespec="seconds")

    api.register_tool(
        "now",
        now,
        "Return the current local date and time.",
        {"type": "object", "properties": {}, "required": []},
    )

    def hello(text=""):
        who = text.split(" ", 1)[-1].strip() if text else "there"
        return f"hello from the example plugin, {who}!"

    api.register_command("hello", hello, "example plugin command")

    def on_startup():
        api.log("example plugin loaded")

    api.on("startup", on_startup)
