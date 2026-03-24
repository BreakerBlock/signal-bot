"""
SIGNAL — Telegram Briefing Bot
Sends a styled PDF briefing to your Telegram every 2 hours.
"""

import anthropic
import requests
import json
import schedule
import time
import os, sys
from datetime import datetime
from io import BytesIO
import pytz

# ── CONFIG — loaded from environment variables ────────────────────────────
def get_env(key):
    val = os.environ.get(key)
    if not val:
        print(f"[SIGNAL] Waiting for env var: {key} ...")
        time.sleep(5)
        val = os.environ.get(key)
    if not val:
        print(f"[SIGNAL] ERROR: {key} not set. Check Railway Variables tab.")
        sys.exit(1)
    return val

ANTHROPIC_API_KEY  = get_env("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = get_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = get_env("TELEGRAM_CHAT_ID")
# ─────────────────────────────────────────────────────────────────────────

IST = pytz.timezone("Asia/Kolkata")

SECTIONS = [
    ("india_politics", "INDIAN POLITICS",    "last 24 hours", (244, 162, 90)),
    ("india_legal",    "COURTS & LAW",       "last 24 hours", (232, 168, 124)),
    ("india_general",  "INDIA",              "last 24 hours", (212, 168, 71)),
    ("global",         "GLOBAL",             "last 24 hours", (155, 142, 196)),
    ("technology",     "TECHNOLOGY",         "last 24 hours", (126, 184, 201)),
    ("science",        "SCIENCE",            "last 24 hours", (184, 201, 126)),
    ("business",       "BUSINESS & ECONOMY", "last 24 hours", (126, 196, 168)),
    ("sports",         "SPORTS",             "last 24 hours", (196, 126, 155)),
]


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

STRICT RULE: Include stories from the last 24 hours across ALL sections. If a section has no fresh news in 24 hours, write "No major developments in the last 24 hours" for that bullet.

Your ENTIRE response must be ONLY a raw JSON object. First character must be {{ and last must be }}.

{{"india_politics":["s1","s2","s3","s4","s5"],"india_legal":["s1","s2","s3","s4","s5"],"india_general":["s1","s2","s3","s4","s5"],"global":["s1","s2","s3","s4","s5"],"technology":["s1","s2","s3","s4","s5"],"science":["s1","s2","s3","s4","s5"],"business":["s1","s2","s3","s4","s5"],"sports":["s1","s2","s3","s4","s5"]}}

Each array: 5-7 strings. Each string: one fact-dense sentence with real names, places, numbers.

india_politics: Last 24 hours — BJP, Congress, AAP, TMC, Modi govt, Parliament, state elections, controversies, minister statements.
india_legal: Supreme Court orders TODAY, High Court rulings, CBI/ED arrests, bail hearings, PIL filings, PMLA, SEBI orders.
india_general: Accidents, cricket, social issues, deaths, trending stories on X today.
global: Breaking internationally — wars, diplomacy, elections, major incidents from last 6 hours.
technology: AI news, big tech, Indian startups, govt digital policy, cybersecurity from TODAY.
science: ISRO, space missions, medical breakthroughs, climate, health alerts from TODAY.
business: Sensex/Nifty numbers today, RBI actions, corporate deals, FII flows, unicorn news.
sports: Cricket (IPL, Test matches, scores), football, kabaddi, Olympics news, Indian athlete achievements, major international sports results from last 24 hours."""


def fetch_briefing():
    now = get_ist_now()
    print(f"[{now.strftime('%H:%M IST')}] Fetching briefing...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Retry up to 3 times on rate limit (429) errors
    message = None
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": build_prompt(now)}]
            )
            break
        except Exception as e:
            if "rate_limit" in str(e).lower() and attempt < 2:
                wait = 60 * (attempt + 1)  # 60s then 120s
                print(f"Rate limit hit. Retrying in {wait}s (attempt {attempt+2}/3)...")
                time.sleep(wait)
            else:
                raise

    raw = ""
    for block in message.content:
        if block.type == "text":
            raw += block.text

    first = raw.index("{")
    last  = raw.rindex("}") + 1
    data  = json.loads(raw[first:last])

    for key, *_ in SECTIONS:
        val = data.get(key, [])
        if isinstance(val, str):
            val = [v.strip() for v in val.split("\n") if v.strip()]
        data[key] = val or ["No data found."]

    return data, now


def generate_pdf(data, now):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
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

    logo_sty    = ParagraphStyle("logo",   fontName="Helvetica-Bold", fontSize=22, textColor=ACCENT, leading=26)
    sub_sty     = ParagraphStyle("sub",    fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10, spaceBefore=2)
    date_sty    = ParagraphStyle("date",   fontName="Helvetica-Bold", fontSize=15, textColor=WHITE, leading=19, spaceBefore=6)
    meta_sty    = ParagraphStyle("meta",   fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=11)
    sec_sty     = ParagraphStyle("sec",    fontName="Helvetica-Bold", fontSize=8.5, textColor=WHITE, leading=12, letterSpacing=1.5)
    win_sty     = ParagraphStyle("win",    fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10)
    bullet_sty  = ParagraphStyle("bullet", fontName="Helvetica", fontSize=9, textColor=TEXT, leading=14, leftIndent=10, spaceBefore=3)
    footer_sty  = ParagraphStyle("footer", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10, alignment=TA_CENTER)

    date_str   = now.strftime("%A, %d %B %Y")
    time_str   = now.strftime("%I:%M %p IST")
    edition_hr = (now.hour // 2) * 2
    edition    = f"EDITION {edition_hr:02d}:00 – {edition_hr+2:02d}:00 IST"

    story = []

    # Header
    story.append(Paragraph("SIGNAL", logo_sty))
    story.append(Paragraph("X INTELLIGENCE BRIEFING  &middot;  INDIA POLITICS &amp; LEGAL FOCUS", sub_sty))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6))
    story.append(Paragraph(date_str, date_sty))
    story.append(Paragraph(f"{edition}  &middot;  Fetched at {time_str}", meta_sty))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=8, spaceAfter=14))

    # Sections
    for key, label, window, rgb in SECTIONS:
        sec_color = colors.Color(rgb[0]/255, rgb[1]/255, rgb[2]/255)
        hex_col   = "%02x%02x%02x" % rgb
        bullets   = data.get(key, [])

        # Label row
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

        # Bullet card
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

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=4, spaceAfter=6))
    story.append(Paragraph(
        f"SIGNAL  &middot;  7 SECTIONS  &middot;  INDIA POLITICS &amp; LEGAL PRIORITY  &middot;  {time_str}",
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
    })
    if not resp.ok:
        print(f"Telegram PDF error: {resp.text}")


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
        print(f"[{now.strftime('%H:%M IST')}] Generating PDF...")
        pdf_buf  = generate_pdf(data, now)
        filename = f"SIGNAL_{now.strftime('%d%b%Y_%H%M')}.pdf"
        caption  = (
            f"📡 *SIGNAL BRIEFING*\n"
            f"_{now.strftime('%d %b %Y')} · {now.strftime('%I:%M %p IST')}_\n"
            f"_Next briefing in 24 hours_"
        )
        send_telegram_pdf(pdf_buf, filename, caption)
        print(f"✓ PDF sent at {now.strftime('%H:%M IST')}")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback; traceback.print_exc()
        try:
            send_error_notification(e)
        except:
            pass


def main():
    once = "--once" in sys.argv
    if once:
        print(f"SIGNAL running once at {get_ist_now().strftime('%H:%M IST')}")
        run_briefing()
    else:
        print("SIGNAL Bot starting (continuous mode)...")
        print("Scheduled every 24 hours. First run immediately.\n")
        run_briefing()
        schedule.every(24).hours.do(run_briefing)
        while True:
            schedule.run_pending()
            time.sleep(30)


if __name__ == "__main__":
    main()
