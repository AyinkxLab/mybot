"""Current weather for a city via wttr.in (no API key)."""


def register(api):
    import urllib.parse
    import urllib.request

    def weather(city):
        url = "https://wttr.in/" + urllib.parse.quote(str(city)) + "?format=3"
        try:
            return urllib.request.urlopen(url, timeout=20).read().decode("utf-8", "replace").strip()
        except Exception as exc:
            return f"ERROR: {exc}"

    api.register_tool(
        "weather",
        weather,
        "Get the current weather for a city.",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
