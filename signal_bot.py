"""
SIGNAL — Telegram Briefing Bot
Sends an India-focused news briefing to your Telegram every 2 hours.

Setup instructions at the bottom of this file.
"""

import anthropic
import requests
import json
import schedule
import time
from datetime import datetime
import pytz

# ── CONFIG — loaded from Railway environment variables ─────────────────────
import os
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
# ───────────────────────────────────────────────────────────────────────────

IST = pytz.timezone("Asia/Kolkata")

SECTION_META = {
    "india_politics": ("🇮🇳 INDIAN POLITICS",    "last 24 hours"),
    "india_legal":    ("⚖️ COURTS & LAW",         "last 6 hours"),
    "india_general":  ("📰 INDIA",                "last 6 hours"),
    "global":         ("🌍 GLOBAL",               "last 6 hours"),
    "technology":     ("💻 TECHNOLOGY",           "last 6 hours"),
    "science":        ("🔬 SCIENCE",              "last 6 hours"),
    "business":       ("📈 BUSINESS & ECONOMY",   "last 6 hours"),
}


def get_ist_now():
    return datetime.now(IST)


def build_prompt(now):
    date_str = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%I:%M %p IST")
    return f"""TODAY IS {date_str}. CURRENT TIME: {time_str}.

You must search for news from the LAST 6 HOURS ONLY. Anything older must be excluded. Do multiple targeted searches:
- Search "site:x.com trending India {date_str}"
- Search "India politics news last 6 hours {date_str}"
- Search "Supreme Court India today {date_str}"
- Search "India breaking news {date_str}"
- Search "Sensex Nifty today {date_str}"
- Search any trending topic you find on X/Twitter right now

STRICT RULE: For INDIA POLITICS only — include stories from the last 24 hours. For ALL OTHER sections — only include stories from the last 6 hours. If a section has no fresh news, write "No major developments in this window" for that bullet.

Your ENTIRE response must be ONLY a raw JSON object. First character must be {{ and last must be }}.

{{"india_politics":["s1","s2","s3","s4","s5"],"india_legal":["s1","s2","s3","s4","s5"],"india_general":["s1","s2","s3","s4","s5"],"global":["s1","s2","s3","s4","s5"],"technology":["s1","s2","s3","s4","s5"],"science":["s1","s2","s3","s4","s5"],"business":["s1","s2","s3","s4","s5"]}}

Each array: 5-7 strings. Each string: one fact-dense sentence with real names, places, numbers.

india_politics: Last 24 hours — BJP, Congress, AAP, TMC, Modi govt, Parliament, state elections, controversies, minister statements.
india_legal: Supreme Court orders TODAY, High Court rulings, CBI/ED arrests, bail hearings, PIL filings, PMLA, SEBI orders.
india_general: Accidents, cricket, social issues, deaths, trending stories on X today.
global: Breaking internationally — wars, diplomacy, elections, major incidents from last 6 hours.
technology: AI news, big tech, Indian startups, govt digital policy, cybersecurity from TODAY.
science: ISRO, space missions, medical breakthroughs, climate, health alerts from TODAY.
business: Sensex/Nifty numbers today, RBI actions, corporate deals, FII flows, unicorn news."""


def fetch_briefing():
    now = get_ist_now()
    print(f"[{now.strftime('%H:%M IST')}] Fetching briefing...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": build_prompt(now)}]
    )

    # Extract text from response
    raw = ""
    for block in message.content:
        if block.type == "text":
            raw += block.text

    # Parse JSON robustly
    first = raw.index("{")
    last  = raw.rindex("}") + 1
    data  = json.loads(raw[first:last])

    # Normalise to lists
    for key in SECTION_META:
        val = data.get(key, [])
        if isinstance(val, str):
            val = [v.strip() for v in val.split("\n") if v.strip()]
        data[key] = val or ["No data found."]

    return data, now


def format_telegram_message(data, now):
    edition_hour = (now.hour // 2) * 2
    edition = f"{edition_hour:02d}:00"
    date_str = now.strftime("%d %b %Y")
    time_str = now.strftime("%I:%M %p IST")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"📡 *SIGNAL BRIEFING*",
        f"_{date_str} · Edition {edition}_",
        f"_Fetched at {time_str}_",
        "━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for key, (label, window) in SECTION_META.items():
        bullets = data.get(key, [])
        lines.append(f"*{label}*  `{window}`")
        for b in bullets:
            # Escape markdown special chars in bullet text
            safe = b.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
            lines.append(f"▸ {safe}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Next briefing in 2 hours_")

    return "\n".join(lines)


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Split into chunks if message too long (Telegram limit: 4096 chars)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        if not resp.ok:
            print(f"Telegram error: {resp.text}")


def send_error_notification(err):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"⚠️ *SIGNAL* — Briefing fetch failed\n\n`{str(err)[:200]}`",
        "parse_mode": "Markdown"
    })


def run_briefing():
    try:
        data, now = fetch_briefing()
        msg = format_telegram_message(data, now)
        send_telegram(msg)
        print(f"✓ Sent at {now.strftime('%H:%M IST')}")
    except Exception as e:
        print(f"✗ Error: {e}")
        try:
            send_error_notification(e)
        except:
            pass


def main():
    import sys
    once = "--once" in sys.argv

    if once:
        # Single run mode — for PythonAnywhere scheduled tasks
        print(f"SIGNAL running once at {get_ist_now().strftime('%H:%M IST')}")
        run_briefing()
    else:
        # Continuous mode — runs every 2 hours
        print("SIGNAL Bot starting (continuous mode)...")
        print(f"Scheduled every 2 hours. First run immediately.\n")
        run_briefing()
        schedule.every(2).hours.do(run_briefing)
        while True:
            schedule.run_pending()
            time.sleep(30)


if __name__ == "__main__":
    main()
