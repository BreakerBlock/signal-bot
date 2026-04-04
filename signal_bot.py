"""
SIGNAL -- Telegram Briefing Bot
Sends a styled PDF briefing to your Telegram every 24 hours.
"""

import anthropic
import requests
import json
import re
import schedule
import time
import os, sys
from datetime import datetime
from io import BytesIO
import pytz

# ── CONFIG ────────────────────────────────────────────────────────────────────
def get_env(key):
    val = os.environ.get(key)
    if not val:
        time.sleep(5)
        val = os.environ.get(key)
    if not val:
        print(f"[SIGNAL] ERROR: {key} not set.")
        sys.exit(1)
    return val

ANTHROPIC_API_KEY      = get_env("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN     = get_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID       = get_env("TELEGRAM_CHAT_ID")       # group -- briefings only
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID")
# NOTE: set TELEGRAM_ALERT_CHAT_ID in Railway to your personal chat ID.
# Until set, errors go to console logs only -- the group is NEVER touched.
# ─────────────────────────────────────────────────────────────────────────────

IST = pytz.timezone("Asia/Kolkata")

SECTIONS = [
    ("india_politics", "INDIAN POLITICS",    "last 12 hours", (244, 162, 90)),
    ("india_legal",    "COURTS & LAW",       "last 12 hours", (232, 168, 124)),
    ("india_general",  "INDIA",              "last 12 hours", (212, 168, 71)),
    ("global",         "GLOBAL",             "last 12 hours", (155, 142, 196)),
    ("technology",     "TECHNOLOGY",         "last 12 hours", (126, 184, 201)),
    ("science",        "SCIENCE",            "last 12 hours", (184, 201, 126)),
    ("business",       "BUSINESS & ECONOMY", "last 12 hours", (126, 196, 168)),
    ("sports",         "SPORTS",             "last 12 hours", (196, 126, 155)),
]

SECTION_SEARCHES = {
    "india_politics": "India politics BJP Congress Modi Parliament ANI PTI",
    "india_legal":    "Supreme Court India High Court ruling LiveLaw barandbench",
    "india_general":  "India news IndiaToday BBCIndia scroll thewire trending",
    "global":         "world news Reuters AP BBC breaking international",
    "technology":     "AI tech news TechCrunch Verge OpenAI Google startup",
    "science":        "science research ISRO space medical Nature EricTopol",
    "business":       "Sensex Nifty RBI rupee markets economy livemint",
    "sports":         "cricket IPL football tennis ESPNcricinfo FabrizioRomano",
}


def get_ist_now():
    return datetime.now(IST)


def build_search_prompt(now):
    """Turn 1: do the searches, no JSON yet."""
    date_str = now.strftime("%A, %d %B %Y")
    time_str = now.strftime("%I:%M %p IST")
    searches = "\n".join(
        f"{i+1}. {label}: search \"{SECTION_SEARCHES[key]} {date_str}\""
        for i, (key, label, _, _) in enumerate(SECTIONS)
    )
    return (
        f"Today is {date_str}, {time_str}.\n\n"
        f"Search for the top news story from the last 12 hours for each topic below. "
        f"Do one search per topic.\n\n{searches}"
    )


def build_json_prompt():
    """Turn 2: convert search results to JSON -- no tools needed."""
    keys = '","'.join(k for k, *_ in SECTIONS)
    return (
        "Based on your search results above, output ONLY a valid JSON object with "
        f"these 8 keys: \"{keys}\". "
        "Each key maps to an array of exactly 5 strings. "
        "Each string is one fact-dense sentence ending with '-- via @Handle'. "
        "No prose, no markdown fences. First character must be { and last must be }."
    )


def clean_bullet(text):
    text = re.sub(r']*>(.*?)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\[\d+[-,]?\d*\]', '', text)
    text = re.sub(r'index="[^"]*"', '', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def fetch_briefing():
    now = get_ist_now()
    print(f"[{now.strftime('%H:%M IST')}] Fetching briefing...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

    # ── Turn 1: search ────────────────────────────────────────────────────────
    turn1 = None
    for attempt in range(3):
        try:
            turn1 = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": build_search_prompt(now)}]
            )
            break
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"Rate limit. Retrying in {wait}s...")
            time.sleep(wait)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(30)

    print(f"[DEBUG] Turn1 stop_reason={turn1.stop_reason}, blocks={[b.type for b in turn1.content]}")

    # ── Turn 2: produce JSON from search results (no tools) ───────────────────
    # Build a clean conversation: user -> assistant (text summaries only) -> user
    # Strip tool_use/tool_result blocks -- only keep text blocks for assistant turn
    assistant_text = "\n".join(
        b.text for b in turn1.content if b.type == "text"
    ).strip()

    # If the model returned nothing useful in text, use a placeholder so
    # the conversation stays valid -- turn 2 will still produce JSON
    if not assistant_text:
        assistant_text = "I have completed the web searches and gathered the results."

    turn2 = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[
            {"role": "user",      "content": build_search_prompt(now)},
            {"role": "assistant", "content": assistant_text},
            {"role": "user",      "content": build_json_prompt()},
        ]
    )

    raw = "".join(b.text for b in turn2.content if b.type == "text")
    print(f"[DEBUG] Turn2 length={len(raw)}, preview={raw[:300]}")

    first = raw.index("{")
    last  = raw.rindex("}") + 1
    data  = json.loads(raw[first:last])

    for key, *_ in SECTIONS:
        val = data.get(key, [])
        if isinstance(val, str):
            val = [v.strip() for v in val.split("\n") if v.strip()]
        cleaned = [
            clean_bullet(b) for b in val
            if clean_bullet(b)
            and "no major development" not in b.lower()
            and "no data" not in b.lower()
        ]
        data[key] = cleaned or ["Updates pending -- check next edition."]

    return data, now


def generate_pdf(data, now):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    HRFlowable, Table, TableStyle)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=16*mm, bottomMargin=16*mm,
    )

    BG      = colors.HexColor("#0a0a0a")
    SURFACE = colors.HexColor("#111111")
    BORDER  = colors.HexColor("#1e1e1e")
    ACCENT  = colors.HexColor("#e8d5a3")
    MUTED   = colors.HexColor("#555550")
    TEXT    = colors.HexColor("#c8c8c0")
    WHITE   = colors.HexColor("#e0e0d8")

    logo_sty   = ParagraphStyle("logo",   fontName="Helvetica-Bold", fontSize=22, textColor=ACCENT, leading=26)
    sub_sty    = ParagraphStyle("sub",    fontName="Helvetica",      fontSize=7,  textColor=MUTED,  leading=10, spaceBefore=2)
    date_sty   = ParagraphStyle("date",   fontName="Helvetica-Bold", fontSize=15, textColor=WHITE,  leading=19, spaceBefore=6)
    meta_sty   = ParagraphStyle("meta",   fontName="Helvetica",      fontSize=7.5,textColor=MUTED,  leading=11)
    sec_sty    = ParagraphStyle("sec",    fontName="Helvetica-Bold", fontSize=8.5,textColor=WHITE,  leading=12, letterSpacing=1.5)
    win_sty    = ParagraphStyle("win",    fontName="Helvetica",      fontSize=7,  textColor=MUTED,  leading=10)
    bullet_sty = ParagraphStyle("bullet", fontName="Helvetica",      fontSize=9,  textColor=TEXT,   leading=14, leftIndent=10, spaceBefore=3)
    footer_sty = ParagraphStyle("footer", fontName="Helvetica",      fontSize=7,  textColor=MUTED,  leading=10, alignment=TA_CENTER)

    date_str   = now.strftime("%A, %d %B %Y")
    time_str   = now.strftime("%I:%M %p IST")
    edition_hr = (now.hour // 2) * 2
    edition    = f"EDITION {edition_hr:02d}:00 - {edition_hr+2:02d}:00 IST"

    story = []
    story.append(Paragraph("SIGNAL", logo_sty))
    story.append(Paragraph("X INTELLIGENCE BRIEFING  &middot;  INDIA POLITICS &amp; LEGAL FOCUS", sub_sty))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph(date_str, date_sty))
    story.append(Paragraph(f"{edition}  &middot;  Fetched at {time_str}", meta_sty))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=14))

    for key, label, window, rgb in SECTIONS:
        sec_color = colors.Color(rgb[0]/255, rgb[1]/255, rgb[2]/255)
        hex_col   = "%02x%02x%02x" % rgb
        bullets   = data.get(key, [])

        hdr = Table([[
            Paragraph(f'<font color="#{hex_col}">&#9646; {label}</font>', sec_sty),
            Paragraph(window.upper(), win_sty),
        ]], colWidths=["75%", "25%"])
        hdr.setStyle(TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN",         (1,0), (1,0),   "RIGHT"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("TOPPADDING",    (0,0), (-1,-1), 0),
        ]))
        story.append(hdr)

        items = []
        for b in bullets:
            safe = b.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            items.append(Paragraph(f'<font color="#{hex_col}">&#9658;</font>  {safe}', bullet_sty))

        card = Table([[items]], colWidths=["100%"])
        card.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), SURFACE),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ("RIGHTPADDING",  (0,0), (-1,-1), 10),
            ("TOPPADDING",    (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 8),
            ("LINEBEFORE",    (0,0), (0,-1),  3, sec_color),
            ("BOX",           (0,0), (-1,-1), 0.5, BORDER),
        ]))
        story.append(card)
        story.append(Spacer(1, 10))

    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=4, spaceAfter=6))
    story.append(Paragraph(
        f"SIGNAL  &middot;  8 SECTIONS  &middot;  INDIA FOCUS  &middot;  {time_str}",
        footer_sty
    ))

    def draw_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_bg, onLaterPages=draw_bg)
    buf.seek(0)
    return buf


def send_telegram_pdf(pdf_buf, filename, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "caption": caption,
        "parse_mode": "Markdown",
    }, files={
        "document": (filename, pdf_buf, "application/pdf")
    }, timeout=30)
    if not resp.ok:
        print(f"Telegram PDF error: {resp.text}")


def send_private_alert(err):
    """Send error to private chat only. If TELEGRAM_ALERT_CHAT_ID is not set,
    log to console only -- the group is never touched."""
    if not TELEGRAM_ALERT_CHAT_ID:
        print(f"[SIGNAL] No TELEGRAM_ALERT_CHAT_ID set -- error logged only: {err}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_ALERT_CHAT_ID,
            "text": f"*SIGNAL error*\n\n`{str(err)[:400]}`",
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as alert_err:
        print(f"[SIGNAL] Failed to send private alert: {alert_err}")


def run_briefing():
    try:
        data, now = fetch_briefing()
        print(f"[{now.strftime('%H:%M IST')}] Generating PDF...")
        pdf_buf  = generate_pdf(data, now)
        filename = f"SIGNAL_{now.strftime('%d%b%Y_%H%M')}.pdf"
        caption  = (
            f"*SIGNAL BRIEFING*\n"
            f"_{now.strftime('%d %b %Y')} - {now.strftime('%I:%M %p IST')}_\n"
            f"_Next briefing in 24 hours_"
        )
        send_telegram_pdf(pdf_buf, filename, caption)
        print(f"[SIGNAL] Sent at {now.strftime('%H:%M IST')}")
    except Exception as e:
        print(f"[SIGNAL] Error: {e}")
        import traceback; traceback.print_exc()
        send_private_alert(e)   # private only -- group stays clean


def main():
    if "--once" in sys.argv:
        print(f"SIGNAL one-shot at {get_ist_now().strftime('%H:%M IST')}")
        run_briefing()
    else:
        print("SIGNAL starting...")
        run_briefing()
        schedule.every(24).hours.do(run_briefing)
        while True:
            schedule.run_pending()
            time.sleep(30)


if __name__ == "__main__":
    main()
