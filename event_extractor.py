import imaplib
import email
from email.header import decode_header
import json
import os
import sqlite3
import requests
from datetime import datetime

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
ACCOUNTS_FILE = "email_accounts.json"
DB_FILE       = "events.db"
OLLAMA_URL    = "http://localhost:11434/api/generate"
OLLAMA_MODEL  = "llama3.2"


# ──────────────────────────────────────────────
#  DATABASE SETUP
# ──────────────────────────────────────────────
def init_db():
    """Create events table if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            email_subject TEXT,
            event_name   TEXT,
            date         TEXT,
            time         TEXT,
            venue        TEXT,
            deadline     TEXT,
            description  TEXT,
            is_event     INTEGER DEFAULT 1,
            user_response TEXT DEFAULT 'pending',
            created_at   TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_event(email_subject, event_data):
    """Save a single extracted event to the database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO events
            (email_subject, event_name, date, time, venue, deadline, description, is_event, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        email_subject,
        event_data.get("event_name", ""),
        event_data.get("date", ""),
        event_data.get("time", ""),
        event_data.get("venue", ""),
        event_data.get("deadline", ""),
        event_data.get("description", ""),
        1 if event_data.get("is_event") else 0,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    conn.commit()
    conn.close()


def load_all_events():
    """Load all saved events from the database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE is_event = 1 ORDER BY created_at DESC")
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    return [dict(zip(columns, row)) for row in rows]


def already_extracted(subject):
    """Check if we already processed an email with this subject."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM events WHERE email_subject = ?", (subject,))
    result = c.fetchone()
    conn.close()
    return result is not None


# ──────────────────────────────────────────────
#  EMAIL HELPERS  (same as before)
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
            decoded.append(part)
    return "".join(decoded)


def get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
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


def fetch_recent_emails(account, count=10):
    print(f"\nConnecting to {account['host']} as {account['email']} ...")
    try:
        mail = imaplib.IMAP4_SSL(account["host"], account["port"])
        mail.login(account["email"], account["password"])
        print("  ✓ Login successful")
    except imaplib.IMAP4.error as e:
        print(f"  ✗ Login failed: {e}")
        return []

    mail.select("INBOX")
    status, data = mail.search(None, "ALL")
    mail_ids = data[0].split()

    if not mail_ids:
        print("  No emails found.")
        mail.logout()
        return []

    recent_ids = mail_ids[-count:]
    recent_ids.reverse()

    emails = []
    for uid in recent_ids:
        status, msg_data = mail.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        emails.append({
            "subject": decode_str(msg.get("Subject", "(no subject)")),
            "from":    decode_str(msg.get("From", "")),
            "date":    decode_str(msg.get("Date", "")),
            "body":    get_body(msg),
        })

    mail.logout()
    return emails


# ──────────────────────────────────────────────
#  OLLAMA  —  EVENT EXTRACTION
# ──────────────────────────────────────────────
def extract_event_with_ollama(email_subject, email_body):
    """
    Send email text to local Ollama llama3.2 and ask it to extract event info.
    Returns a dict with event fields, or None if no event found.
    """

    # Trim body to 1500 chars to keep the prompt fast
    body_preview = email_body[:1500]

    prompt = f"""You are an assistant that reads emails and extracts event information.

Read the email below and extract event details. Reply ONLY with a valid JSON object — no explanation, no extra text.

If the email contains an event, meeting, seminar, workshop, fest, deadline, or any scheduled activity, return:
{{
  "is_event": true,
  "event_name": "name of the event",
  "date": "date if mentioned, else empty string",
  "time": "time if mentioned, else empty string",
  "venue": "venue or location if mentioned, else empty string",
  "deadline": "registration or submission deadline if any, else empty string",
  "description": "one sentence summary of the event"
}}

If the email is NOT about any event (e.g. just a newsletter, spam, personal chat), return:
{{
  "is_event": false
}}

EMAIL SUBJECT: {email_subject}
EMAIL BODY:
{body_preview}

Reply with JSON only:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        raw_text = response.json().get("response", "").strip()

        # Extract JSON from response (sometimes model adds extra text)
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        if start == -1 or end == 0:
            return None

        json_str   = raw_text[start:end]
        event_data = json.loads(json_str)
        return event_data

    except requests.exceptions.ConnectionError:
        print("  ✗ Ollama is not running! Start it with: ollama serve")
        return None
    except json.JSONDecodeError:
        print("  ✗ Could not parse AI response as JSON, skipping.")
        return None
    except Exception as e:
        print(f"  ✗ Ollama error: {e}")
        return None


# ──────────────────────────────────────────────
#  DISPLAY
# ──────────────────────────────────────────────
def display_events(events):
    if not events:
        print("\n  No events found yet.")
        return

    print(f"\n{'═' * 65}")
    print(f"  📅  Extracted Events  ({len(events)} total)")
    print(f"{'═' * 65}")

    for i, ev in enumerate(events, 1):
        print(f"\n[{i}] {ev['event_name'] or '(unnamed event)'}")
        print(f"    From email : {ev['email_subject']}")
        if ev['date']:        print(f"    Date       : {ev['date']}")
        if ev['time']:        print(f"    Time       : {ev['time']}")
        if ev['venue']:       print(f"    Venue      : {ev['venue']}")
        if ev['deadline']:    print(f"    Deadline   : {ev['deadline']}")
        if ev['description']: print(f"    Summary    : {ev['description']}")
        print(f"    Status     : {ev['user_response']}")
        print(f"    {'─' * 58}")


# ──────────────────────────────────────────────
#  MAIN FLOW
# ──────────────────────────────────────────────
def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r") as f:
            return json.load(f)
    return []


def process_emails(account):
    """Fetch emails → run each through Ollama → save events to DB."""
    emails = fetch_recent_emails(account, count=10)
    if not emails:
        return

    print(f"\n  Running AI extraction on {len(emails)} emails...\n")
    found = 0

    for em in emails:
        subject = em["subject"]

        # Skip if already processed
        if already_extracted(subject):
            print(f"  ↷  Skipping (already processed): {subject[:55]}")
            continue

        print(f"  🔍 Analysing: {subject[:55]}")
        event_data = extract_event_with_ollama(subject, em["body"])

        if event_data is None:
            print(f"      → AI error, skipped")
            continue

        if event_data.get("is_event"):
            save_event(subject, event_data)
            print(f"      ✓ Event saved: {event_data.get('event_name', '?')}")
            found += 1
        else:
            print(f"      – No event detected")

    print(f"\n  Done. {found} new event(s) extracted and saved.")


def main():
    init_db()

    print("╔══════════════════════════════════════════════╗")
    print("║   📧 → 📅  Email Event Extractor (Ollama)   ║")
    print("╚══════════════════════════════════════════════╝")

    accounts = load_accounts()
    if not accounts:
        print("\n  No accounts found. Please run email_reader.py first to add an account.")
        return

    # If only one account, use it directly
    if len(accounts) == 1:
        account = accounts[0]
        print(f"\n  Using account: {account['nickname']} ({account['email']})")
    else:
        print("\n── Saved Accounts ───────────────────────────")
        for i, acc in enumerate(accounts, 1):
            print(f"  [{i}] {acc['nickname']}  ({acc['email']})")
        choice = int(input("\nChoose account: ")) - 1
        account = accounts[choice]

    while True:
        print("\n── What do you want to do? ──────────────────")
        print("  [1] Scan emails and extract events")
        print("  [2] View all saved events")
        print("  [0] Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            process_emails(account)
        elif choice == "2":
            events = load_all_events()
            display_events(events)
        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("  Invalid choice.")


if __name__ == "__main__":
    main()