from flask import Flask, jsonify, request, send_from_directory
import sqlite3
import json
import os
import imaplib
import email
from email.header import decode_header
import requests
from datetime import datetime
import threading
from calendar_helper import add_event_to_calendar

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
ACCOUNTS_FILE = "email_accounts.json"
DB_FILE       = "events.db"
OLLAMA_URL    = "http://localhost:11434/api/generate"
OLLAMA_MODEL  = "llama3.2"

app = Flask(__name__, static_folder="static")


# ──────────────────────────────────────────────
#  DATABASE
# ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email_subject TEXT,
            email_from    TEXT,
            email_date    TEXT,
            email_body    TEXT,
            event_name    TEXT,
            date          TEXT,
            time          TEXT,
            venue         TEXT,
            deadline      TEXT,
            description   TEXT,
            is_event      INTEGER DEFAULT 1,
            user_response TEXT DEFAULT 'pending',
            calendar_link TEXT DEFAULT '',
            created_at    TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS emails_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT,
            sender      TEXT,
            date        TEXT,
            body        TEXT,
            processed   INTEGER DEFAULT 0,
            event_count INTEGER DEFAULT 0,
            fetched_at  TEXT
        )
    """)
    # Tracks every attend/dismiss action for interest learning
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_interests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            category   TEXT NOT NULL,
            action     TEXT NOT NULL,   -- 'attend' or 'dismiss'
            event_name TEXT,
            logged_at  TEXT
        )
    """)
    # Safe column upgrades for existing databases
    for col, definition in [
        ("calendar_link",  "TEXT DEFAULT ''"),
        ("category",       "TEXT DEFAULT 'general'"),
        ("priority",       "TEXT DEFAULT 'optional'"),
        ("recommendation", "TEXT DEFAULT 'neutral'"),
    ]:
        try:
            c.execute(f"ALTER TABLE events ADD COLUMN {col} {definition}")
        except Exception:
            pass
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────
#  EMAIL HELPERS
# ──────────────────────────────────────────────
def decode_str(value):
    if value is None:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


def get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
               "attachment" not in str(part.get("Content-Disposition", "")):
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return body.strip()


def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r") as f:
            return json.load(f)
    return []


def fetch_emails_from_imap(account, count=20):
    try:
        mail = imaplib.IMAP4_SSL(account["host"], account["port"])
        mail.login(account["email"], account["password"])
    except Exception as e:
        return [], str(e)

    mail.select("INBOX")
    status, data = mail.search(None, "ALL")
    mail_ids = data[0].split()

    if not mail_ids:
        mail.logout()
        return [], None

    recent_ids = mail_ids[-count:]
    recent_ids.reverse()

    emails = []
    for uid in recent_ids:
        try:
            status, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            emails.append({
                "subject": decode_str(msg.get("Subject", "(no subject)")),
                "sender":  decode_str(msg.get("From", "")),
                "date":    decode_str(msg.get("Date", "")),
                "body":    get_body(msg),
            })
        except Exception:
            continue

    mail.logout()
    return emails, None


def cache_emails(emails):
    conn = get_db()
    c = conn.cursor()
    inserted = 0
    for em in emails:
        c.execute("SELECT id FROM emails_cache WHERE subject=? AND sender=?",
                  (em["subject"], em["sender"]))
        if c.fetchone():
            continue
        c.execute("""
            INSERT INTO emails_cache (subject, sender, date, body, fetched_at)
            VALUES (?, ?, ?, ?, ?)
        """, (em["subject"], em["sender"], em["date"], em["body"],
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        inserted += 1
    conn.commit()
    conn.close()
    return inserted


# ──────────────────────────────────────────────
#  OLLAMA
# ──────────────────────────────────────────────
def extract_event_with_ollama(subject, body):
    prompt = f"""You are an assistant that reads emails and extracts event information.

Read the email below and extract event details. Reply ONLY with a valid JSON object — no explanation, no extra text, no markdown.

If the email contains an event, meeting, seminar, workshop, fest, deadline, or any scheduled activity, return:
{{
  "is_event": true,
  "event_name": "name of the event",
  "date": "date if mentioned, else empty string",
  "time": "time if mentioned, else empty string",
  "venue": "venue or location if mentioned, else empty string",
  "deadline": "registration or submission deadline if any, else empty string",
  "description": "one sentence summary of the event",
  "category": "one of: academics, clubs, placements, wellness, finance, meetings, general",
  "priority": "one of: urgent, important, optional"
}}

Category guide:
- academics  : lectures, exams, assignments, seminars, workshops, courses
- clubs      : cultural events, fests, club meetings, sports, competitions
- placements : internships, job drives, career fairs, company visits, interviews
- wellness   : health camps, counselling, sports, gym, mental health
- finance    : fees, scholarships, stipends, financial deadlines
- meetings   : team meetings, committee meetings, faculty meetings
- general    : anything that does not fit above

Priority guide:
- urgent     : deadline within 48 hours, exam tomorrow, fee last date, interview
- important  : deadline within a week, major event, compulsory attendance
- optional   : optional workshop, informal meetup, general info

If the email is NOT about any event, return:
{{
  "is_event": false
}}

EMAIL SUBJECT: {subject}
EMAIL BODY:
{body[:1500]}

Reply with JSON only:"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=90,
        )
        raw   = resp.json().get("response", "").strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        return json.loads(raw[start:end])
    except Exception:
        return None


def process_unprocessed_emails():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM emails_cache WHERE processed = 0 LIMIT 10")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    for row in rows:
        result = extract_event_with_ollama(row["subject"], row["body"])
        conn = get_db()
        c = conn.cursor()
        if result and result.get("is_event"):
            c.execute("""
                INSERT INTO events
                    (email_subject, email_from, email_date, email_body,
                     event_name, date, time, venue, deadline, description,
                     is_event, user_response, calendar_link,
                     category, priority, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'pending', '', ?, ?, ?)
            """, (
                row["subject"], row["sender"], row["date"], row["body"],
                result.get("event_name",""),  result.get("date",""),
                result.get("time",""),         result.get("venue",""),
                result.get("deadline",""),     result.get("description",""),
                result.get("category","general"),
                result.get("priority","normal"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))
            c.execute("UPDATE emails_cache SET processed=1, event_count=1 WHERE id=?", (row["id"],))
        else:
            c.execute("UPDATE emails_cache SET processed=1, event_count=0 WHERE id=?", (row["id"],))
        conn.commit()
        conn.close()



# ──────────────────────────────────────────────
#  INTEREST LEARNING
# ──────────────────────────────────────────────
def get_user_interests():
    """
    Returns a dict of category → score based on past attend/dismiss actions.
    attend = +2 points, dismiss = -1 point. Returns top interests.
    """
    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT category,
               SUM(CASE WHEN action='attend'  THEN 2 ELSE 0 END) -
               SUM(CASE WHEN action='dismiss' THEN 1 ELSE 0 END) AS score,
               COUNT(*) as total
        FROM user_interests
        GROUP BY category
        ORDER BY score DESC
    """)
    rows = c.fetchall()
    conn.close()
    return {row[0]: {"score": row[1], "total": row[2]} for row in rows}


def score_event_recommendation(event_name, category, description, interests):
    """
    Use Ollama to decide if an event matches user interests.
    Returns 'recommended', 'neutral', or 'not_for_you'.
    Falls back to rule-based scoring if Ollama fails.
    """
    if not interests:
        return "neutral"

    # Build interest summary for prompt
    liked    = [c for c, d in interests.items() if d["score"] >= 2]
    disliked = [c for c, d in interests.items() if d["score"] < 0]

    # Fast rule-based fallback (no AI needed for clear cases)
    if category in liked:
        return "recommended"
    if category in disliked:
        return "not_for_you"

    # Use Ollama for ambiguous cases
    interest_text = ", ".join(liked) if liked else "none recorded yet"
    dislike_text  = ", ".join(disliked) if disliked else "none"

    prompt = f"""You are a personal event recommendation assistant.

User's liked event categories: {interest_text}
User's disliked categories: {dislike_text}

Event to evaluate:
- Name: {event_name}
- Category: {category}
- Description: {description}

Based on the user's interest pattern, classify this event.
Reply with ONLY one word — exactly one of: recommended, neutral, not_for_you"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        result = resp.json().get("response", "").strip().lower()
        if "recommended" in result:   return "recommended"
        if "not_for_you" in result:   return "not_for_you"
        return "neutral"
    except Exception:
        return "neutral"


def update_recommendations():
    """
    Background job: re-score all pending events using current interest profile.
    Runs every time user marks attend/dismiss.
    """
    interests = get_user_interests()
    if not interests:
        return   # no data yet — nothing to score

    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT id, event_name, category, description
        FROM events
        WHERE is_event=1 AND user_response='pending'
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    for ev in rows:
        rec = score_event_recommendation(
            ev["event_name"] or "",
            ev["category"]   or "general",
            ev["description"] or "",
            interests
        )
        conn = get_db()
        c    = conn.cursor()
        c.execute("UPDATE events SET recommendation=? WHERE id=?", (rec, ev["id"]))
        conn.commit()
        conn.close()


# ──────────────────────────────────────────────
#  ROUTES
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "dashboard.html")


@app.route("/api/emails")
def api_emails():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id,subject,sender,date,body,processed,event_count FROM emails_cache ORDER BY id DESC LIMIT 30")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/fetch-emails", methods=["POST"])
def api_fetch_emails():
    accounts = load_accounts()
    if not accounts:
        return jsonify({"error": "No accounts configured"}), 400
    emails, err = fetch_emails_from_imap(accounts[0], count=20)
    if err:
        return jsonify({"error": err}), 500
    inserted = cache_emails(emails)
    t = threading.Thread(target=process_unprocessed_emails)
    t.daemon = True
    t.start()
    return jsonify({"fetched": len(emails), "new": inserted})


@app.route("/api/events")
def api_events():
    f    = request.args.get("filter",   "all")
    cat  = request.args.get("category", "all")
    pri  = request.args.get("priority", "all")

    query  = "SELECT * FROM events WHERE is_event=1"
    params = []

    if f == "pending":
        query += " AND user_response='pending'"
    elif f == "attending":
        query += " AND user_response='attend'"

    if cat != "all":
        query += " AND category=?"
        params.append(cat)

    if pri != "all":
        query += " AND priority=?"
        params.append(pri)

    query += " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'important' THEN 2 ELSE 3 END, id DESC"

    conn = get_db()
    c = conn.cursor()
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


# ── SUMMARY BAR ──
@app.route("/api/summary")
def api_summary():
    from datetime import date, timedelta
    today     = date.today().isoformat()
    tomorrow  = (date.today() + timedelta(days=1)).isoformat()
    week_end  = (date.today() + timedelta(days=7)).isoformat()

    conn = get_db()
    c    = conn.cursor()

    # Total events
    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1")
    total = c.fetchone()[0]

    # By priority
    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1 AND priority='urgent'")
    urgent = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1 AND priority='important'")
    important = c.fetchone()[0]

    # By category counts
    c.execute("""
        SELECT category, COUNT(*) as cnt
        FROM events WHERE is_event=1
        GROUP BY category ORDER BY cnt DESC
    """)
    by_category = {row[0]: row[1] for row in c.fetchall()}

    # Attending
    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1 AND user_response='attend'")
    attending = c.fetchone()[0]

    # Pending response
    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1 AND user_response='pending'")
    pending = c.fetchone()[0]

    conn.close()

    # Build human-readable summary sentence
    parts = []
    if urgent:
        parts.append(f"🔴 {urgent} urgent")
    if important:
        parts.append(f"🟡 {important} important")
    top_cats = sorted(by_category.items(), key=lambda x: -x[1])[:2]
    for cat, cnt in top_cats:
        parts.append(f"{cnt} {cat}")
    if attending:
        parts.append(f"✓ {attending} attending")
    if pending:
        parts.append(f"⏳ {pending} awaiting response")

    sentence = "  ·  ".join(parts) if parts else "No events yet"

    return jsonify({
        "sentence":    sentence,
        "total":       total,
        "urgent":      urgent,
        "important":   important,
        "attending":   attending,
        "pending":     pending,
        "by_category": by_category,
    })


@app.route("/api/events/<int:event_id>/response", methods=["PATCH"])
def api_event_response(event_id):
    data   = request.get_json()
    action = data.get("response")
    if action not in ("attend", "dismiss", "pending"):
        return jsonify({"error": "Invalid response"}), 400

    conn = get_db()
    c    = conn.cursor()

    # Save response
    c.execute("UPDATE events SET user_response=? WHERE id=?", (action, event_id))

    # Log to interest table (only for attend/dismiss, not pending)
    if action in ("attend", "dismiss"):
        c.execute("SELECT event_name, category FROM events WHERE id=?", (event_id,))
        row = c.fetchone()
        if row:
            c.execute("""
                INSERT INTO user_interests (category, action, event_name, logged_at)
                VALUES (?, ?, ?, ?)
            """, (row[1] or "general", action, row[0],
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()

    # Background: re-score all pending events with updated interests
    t = threading.Thread(target=update_recommendations)
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "id": event_id, "response": action})


# ── ADD TO GOOGLE CALENDAR ──
@app.route("/api/events/<int:event_id>/add-to-calendar", methods=["POST"])
def api_add_to_calendar(event_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?", (event_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Event not found"}), 404

    ev     = dict(row)
    result = add_event_to_calendar(
        event_name  = ev.get("event_name", "Event"),
        date_str    = ev.get("date", ""),
        time_str    = ev.get("time", ""),
        venue       = ev.get("venue", ""),
        description = ev.get("description", ""),
    )

    if result["success"]:
        # Save calendar link + mark attending
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "UPDATE events SET user_response='attend', calendar_link=? WHERE id=?",
            (result["calendar_link"], event_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": result["message"], "link": result["calendar_link"]})
    else:
        return jsonify({"ok": False, "error": result["message"]}), 500


@app.route("/api/status")
def api_status():
    accounts = load_accounts()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM emails_cache");          email_count        = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM events WHERE is_event=1"); event_count      = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM emails_cache WHERE processed=0"); pending   = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM events WHERE calendar_link!=''"); on_cal   = c.fetchone()[0]
    conn.close()
    try:
        requests.get("http://localhost:11434", timeout=2)
        ollama_ok = True
    except Exception:
        ollama_ok = False
    return jsonify({
        "accounts":           len(accounts),
        "emails_cached":      email_count,
        "events_extracted":   event_count,
        "pending_processing": pending,
        "on_calendar":        on_cal,
        "ollama_running":     ollama_ok,
    })


@app.route("/api/process", methods=["POST"])
def api_process():
    t = threading.Thread(target=process_unprocessed_emails)
    t.daemon = True
    t.start()
    return jsonify({"ok": True})


# ── USER INTERESTS ──
@app.route("/api/interests")
def api_interests():
    """Returns user interest profile + recent interest log."""
    interests = get_user_interests()

    conn = get_db()
    c    = conn.cursor()
    c.execute("""
        SELECT category, action, event_name, logged_at
        FROM user_interests
        ORDER BY logged_at DESC LIMIT 20
    """)
    history = [dict(zip(["category","action","event_name","logged_at"], r))
               for r in c.fetchall()]
    conn.close()

    # Build liked / disliked lists for the UI
    liked    = [cat for cat, d in interests.items() if d["score"] >= 2]
    disliked = [cat for cat, d in interests.items() if d["score"] < 0]

    return jsonify({
        "interests": interests,
        "liked":     liked,
        "disliked":  disliked,
        "history":   history,
        "has_data":  len(history) > 0,
    })


# ── NOTIFICATIONS ──
@app.route("/api/notifications")
def api_notifications():
    """
    Returns events the user is attending, with a urgency label based
    on how far away they are. Does NOT require calendar_link — just user_response='attend'.
    """
    from dateutil import parser as dateparser   # pip install python-dateutil

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, event_name, date, time, venue, description
        FROM events
        WHERE is_event=1 AND user_response='attend'
        ORDER BY id DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    now      = datetime.now()
    notifs   = []

    for ev in rows:
        date_str = (ev.get("date") or "").strip()
        time_str = (ev.get("time") or "").strip()

        # Try to parse a real datetime
        event_dt = None
        try:
            combined = date_str
            if time_str:
                # Remove timezone labels and time ranges
                t_clean = time_str.replace('–','-').split('-')[0].strip()
                for tz in ['EST','IST','GMT','UTC','PST','CST','MST']:
                    t_clean = t_clean.replace(tz,'').strip()
                combined = date_str + " " + t_clean
            event_dt = dateparser.parse(combined, dayfirst=False)
        except Exception:
            pass

        # Determine urgency + label
        if event_dt:
            diff_min = (event_dt - now).total_seconds() / 60

            if diff_min < 0:
                # Already passed — skip
                continue
            elif diff_min <= 10:
                urgency    = "now"
                time_label = f"Starting in {int(diff_min)} min!"
            elif diff_min <= 60:
                urgency    = "soon"
                time_label = f"In {int(diff_min)} minutes"
            elif diff_min <= 1440:   # today (within 24h)
                hours = int(diff_min // 60)
                mins  = int(diff_min % 60)
                urgency    = "today"
                time_label = f"Today in {hours}h {mins}m" if hours else f"Today in {mins}m"
            elif diff_min <= 10080:  # within 7 days
                days = int(diff_min // 1440)
                urgency    = "upcoming"
                time_label = f"In {days} day{'s' if days>1 else ''}"
            else:
                urgency    = "upcoming"
                time_label = f"Upcoming · {date_str}"
        else:
            # No parseable date — show as upcoming
            urgency    = "upcoming"
            time_label = f"Upcoming · {date_str}" if date_str else "Date not set"

        notifs.append({
            "id":         ev["id"],
            "event_name": ev["event_name"] or "Unnamed Event",
            "date":       ev["date"]  or "",
            "time":       ev["time"]  or "",
            "venue":      ev["venue"] or "",
            "urgency":    urgency,
            "time_label": time_label,
        })

    # Sort: now → soon → today → upcoming
    urgency_order = {"now":0, "soon":1, "today":2, "upcoming":3}
    notifs.sort(key=lambda x: urgency_order.get(x["urgency"], 4))

    return jsonify(notifs)


# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    os.makedirs("static", exist_ok=True)
    print("\n╔══════════════════════════════════════════════╗")
    print("║   🚀  EventLink Server starting...          ║")
    print("║   Open  http://localhost:5000  in browser   ║")
    print("╚══════════════════════════════════════════════╝\n")
    app.run(debug=True, port=5000)