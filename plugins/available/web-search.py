"""Search the web via DuckDuckGo's HTML endpoint (no API key)."""


def register(api):
    import html
    import re
    import urllib.parse
    import urllib.request

    def web_search(query, max_results=5):
        url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(str(query))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        except Exception as exc:
            return f"ERROR: {exc}"
        matches = re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page)
        lines = []
        for href, title in matches[: int(max_results)]:
            title = html.unescape(re.sub("<.*?>", "", title)).strip()
            lines.append(f"- {title}\n  {href}")
        return "\n".join(lines) or "(no results)"

    api.register_tool(
        "web_search",
        web_search,
        "Search the web via DuckDuckGo and return the top results (title + URL).",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    )
