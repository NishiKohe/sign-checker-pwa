from __future__ import annotations

import requests
import collector_v4 as base

# Melonbooks is more restrictive toward obvious crawler UAs / GitHub-hosted requests.
# Keep the normal collector behavior for other sources, but send browser-like headers
# and a warm-up request for melonbooks URLs.
BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"
)

ORIGINAL_GET = base.get
MELON = requests.Session()
MELON.headers.update({
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.5",
    "Referer": "https://www.melonbooks.co.jp/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
})

_warmed = False


def resilient_get(url: str, params: dict | None = None) -> str:
    global _warmed
    if "melonbooks.co.jp" not in url:
        return ORIGINAL_GET(url, params)

    if not _warmed:
        try:
            MELON.get("https://www.melonbooks.co.jp/", timeout=25)
        except Exception as e:
            print("[melon:warmup]", e)
        _warmed = True

    # First attempt: browser-like session.
    try:
        r = MELON.get(url, params=params, timeout=25)
        r.raise_for_status()
        return r.text
    except Exception as first:
        print("[melon:browser-attempt]", url, first)

    # Second attempt: desktop UA. Some WAF rules treat mobile/browser families differently.
    desktop_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.6",
        "Referer": "https://www.melonbooks.co.jp/",
    }
    r = requests.get(url, params=params, headers=desktop_headers, timeout=25)
    r.raise_for_status()
    return r.text


base.get = resilient_get

if __name__ == "__main__":
    base.main()
