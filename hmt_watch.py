#!/usr/bin/env python3
"""Telegram alert when watched HMT watches come in stock (.store / .in).

Run from cron. Alerts only on state change (out -> in, or check breaks), so no spam.
Config: env TG_TOKEN, TG_CHAT (put them in ~/hmt-watch/env).
"""
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

URLS = {  # url -> name shown in the alert
    "https://www.hmtwatches.store/product/44333eb5-32ae-4189-85ab-209a8a451249": "Janata Automatic White (.store)",
    "https://www.hmtwatches.store/product/5cb806d1-3afa-4511-80b4-49e457c1cbab": "Pilot Automatic Black (.store)",
    "https://www.hmtwatches.in/product-1246-hmt-pilot-automatic-ls-black": "Pilot Automatic LS Black (.in)",
    "https://www.hmtwatches.in/product-1247-hmt-pilot-automatic-ls-black-black-strap": "Pilot Automatic LS Black, black strap (.in)",
    "https://www.hmtwatches.in/product-1115-hmt-janata-automatic-white": "Janata Automatic White (.in)",
}
STATE = Path(__file__).with_name("state.json")
IST = timezone(timedelta(hours=5, minutes=30))
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
    # .in (Laravel): out-of-stock product shows a "Notify Me" button (id="notifyMe") in the
    # product's action block. Every page also has "Add To Cart" in quick-view modals, so don't key on that.
    if 'id="is_add_to_cart"' not in html:
        return "unknown"
    return "out" if 'id="notifyMe"' in html else "in"


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


def check(state):
    for url, name in URLS.items():
        try:
            s = status(url, fetch(url))
        except Exception as e:
            s = "unknown"
            print(url, "fetch error:", e, file=sys.stderr)
        print(url, s)
        if s != state.get(url):
            if s == "in":
                telegram(f"🟢 HMT {name} IN STOCK\n{url}")
            elif s == "unknown":
                telegram(f"⚠️ HMT watcher can't read stock status for {name} (blocked or page changed)\n{url}")
            elif state.get(url) == "in":
                telegram(f"🔴 HMT {name} back out of stock\n{url}")
            state[url] = s


def main():
    # GitHub drops/delays most scheduled runs (saw 2 of ~40 fire in a day), so each run
    # loops ~5.5h itself (job limit 6h, free on public repo): every 3 min by day, 15 min at night.
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    start = time.time()
    while True:
        check(state)
        now = datetime.now(IST)
        today = now.strftime("%Y-%m-%d")
        if now.hour >= 8 and state.get("_heartbeat") != today:
            lines = "\n".join(f"{n}: {state.get(u)}" for u, n in URLS.items())
            telegram(f"✅ HMT watcher alive ({today})\n{lines}")
            state["_heartbeat"] = today  # changes daily -> commit -> schedule never auto-paused
        STATE.write_text(json.dumps(state, indent=1))
        if os.environ.get("HC_URL"):  # healthchecks.io dead-man switch: alerts if pings stop
            subprocess.run(["curl", "-sf", "-m", "10", "--retry", "3", os.environ["HC_URL"]], capture_output=True)
        if time.time() - start > 320 * 60:
            break
        time.sleep(180 if 8 <= now.hour < 22 else 900)


def demo():
    st = "https://www.hmtwatches.store/x"
    btn = '<button class="a" disabled="" role="button" data-testid="buybuttonswidget-add-to-cart-button">{}</button>'
    assert status(st, btn.format("Out of Stock")) == "out"
    assert status(st, btn.replace(' disabled=""', "").format("Add to Cart")) == "in"
    assert status(st, "<html>blocked</html>") == "unknown"
    act = '<input type="hidden" id="is_add_to_cart" value="1">{}<button>Add To Cart</button>'
    assert status("https://www.hmtwatches.in/p", act.format('<a id="notifyMe" onclick="notifyMe(1)">Notify Me</a>')) == "out"
    assert status("https://www.hmtwatches.in/p", act.format("")) == "in"
    assert status("https://www.hmtwatches.in/p", "Too Many Requests") == "unknown"
    print("demo ok")


if __name__ == "__main__":
    demo() if sys.argv[1:] == ["--test"] else main()
