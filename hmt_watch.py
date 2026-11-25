#!/usr/bin/env python3
"""Telegram alert when HMT Janata Automatic White comes in stock (.store / .in).

Run from cron. Alerts only on state change (out -> in, or check breaks), so no spam.
Config: env TG_TOKEN, TG_CHAT (put them in ~/hmt-watch/env).
"""
import json, os, re, subprocess, sys
from pathlib import Path

URLS = [
    "https://www.hmtwatches.store/product/44333eb5-32ae-4189-85ab-209a8a451249",
    # Add the .in product URL here once it's listed, e.g.
    # "https://www.hmtwatches.in/product-NNNN-hmt-janata-automatic-white",
]
STATE = Path(__file__).with_name("state.json")
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def status(url, html):
    """Return 'in', 'out' or 'unknown' (markup changed / blocked)."""
    if "hmtwatches.store" in url:
        # Server-rendered buy button: text "Out of Stock" + disabled when unavailable.
        marker = 'data-testid="buybuttonswidget-add-to-cart-button">'
        i = html.find(marker)
        if i < 0:
            return "unknown"
        label = html[i + len(marker):html.find("<", i + len(marker))].lower()
        tag = html[html.rfind("<button", 0, i):i]
        return "out" if "out of stock" in label or 'disabled=""' in tag else "in"
    # .in (Laravel site). ponytail: text heuristic, unverified on a live in-stock page.
    if re.search(r"(?i)stock awaited|out of stock|sold out", html):
        return "out"
    return "in" if re.search(r"(?i)add to cart|buy now", html) else "unknown"


def fetch(url):
    # curl, not urllib: host IPv6 is broken and urllib tries each AAAA serially; curl falls back to v4.
    hdrs = [a for k, v in UA.items() for a in ("-H", f"{k}: {v}")]
    return subprocess.run(["curl", "-sfL", "-m", "45", *hdrs, url],
                          capture_output=True, check=True).stdout.decode("utf-8", "replace")


def telegram(text):
    subprocess.run(["curl", "-sf", "-m", "30", "--data-urlencode", f"chat_id={os.environ['TG_CHAT']}",
                    "--data-urlencode", f"text={text}",
                    f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage"],
                   check=True, capture_output=True)


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    for url in URLS:
        try:
            s = status(url, fetch(url))
        except Exception as e:
            s = "unknown"
            print(url, "fetch error:", e, file=sys.stderr)
        print(url, s)
        if s != state.get(url):
            if s == "in":
                telegram(f"🟢 HMT Janata Automatic White IN STOCK\n{url}")
            elif s == "unknown":
                telegram(f"⚠️ HMT watcher can't read stock status (blocked or page changed)\n{url}")
            elif state.get(url) == "in":
                telegram(f"🔴 Back out of stock\n{url}")
            state[url] = s
    STATE.write_text(json.dumps(state, indent=1))


def demo():
    st = "https://www.hmtwatches.store/x"
    btn = '<button class="a" disabled="" role="button" data-testid="buybuttonswidget-add-to-cart-button">{}</button>'
    assert status(st, btn.format("Out of Stock")) == "out"
    assert status(st, btn.replace(' disabled=""', "").format("Add to Cart")) == "in"
    assert status(st, "<html>blocked</html>") == "unknown"
    assert status("https://www.hmtwatches.in/p", "Stock Awaited") == "out"
    assert status("https://www.hmtwatches.in/p", "<button>Add to Cart</button>") == "in"
    print("demo ok")


if __name__ == "__main__":
    demo() if sys.argv[1:] == ["--test"] else main()
