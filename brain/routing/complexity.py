def score(prompt: str):
    p = prompt.lower()
    words = prompt.split()

    code_kw = ("def", "class", "function", "import", "bug", "error", "traceback")
    if any(k in p for k in code_kw):
        return "code"

    scrape_kw = ("url", "scrape", "website", "http")
    if any(k in p for k in scrape_kw):
        return "scrape"

    tier5 = ("medical", "legal", "finance", "investment", "diagnose", "contract")
    if any(k in p for k in tier5):
        return 5

    tier4 = ("explain", "analyze", "compare", "why", "how does", "summarize")
    if any(k in p for k in tier4):
        return 4

    tier3 = ("search", "find", "news", "latest", "current", "today", "weather", "web")
    if any(k in p for k in tier3):
        return 3

    if len(words) < 15:
        return 1

    return 2
