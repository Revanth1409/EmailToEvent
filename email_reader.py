import imaplib
import email
from email.header import decode_header
import json
import os
import getpass

# ──────────────────────────────────────────────
#  ACCOUNTS FILE  (saved locally, never shared)
# ──────────────────────────────────────────────
ACCOUNTS_FILE = "email_accounts.json"


def load_accounts():
    """Load saved email accounts from local JSON file."""
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r") as f:
            return json.load(f)
    return []


def save_accounts(accounts):
    """Save accounts list to local JSON file."""
    with open(ACCOUNTS_FILE, "w") as f:
        json.dump(accounts, f, indent=2)
    print(f"  ✓ Saved to {ACCOUNTS_FILE}")


def add_account():
    """Interactively add a new email account."""
    print("\n── Add New Account ──────────────────────────")
    print("NOTE: For Gmail you need an App Password, NOT your regular password.")
    print("Get one at: myaccount.google.com → Security → 2-Step Verification → App passwords\n")

    email_addr = input("Enter email address: ").strip()
    app_password = getpass.getpass("Enter App Password (16 chars, no spaces): ").strip()

    # Auto-detect IMAP server from email domain
    domain = email_addr.split("@")[-1].lower()
    imap_servers = {
        "gmail.com":    ("imap.gmail.com",    993),
        "outlook.com":  ("imap-mail.outlook.com", 993),
        "hotmail.com":  ("imap-mail.outlook.com", 993),
        "yahoo.com":    ("imap.mail.yahoo.com",  993),
        "icloud.com":   ("imap.mail.me.com",      993),
    }
    if domain in imap_servers:
        host, port = imap_servers[domain]
        print(f"  ✓ Auto-detected server: {host}:{port}")
    else:
        host = input("IMAP server (e.g. imap.gmail.com): ").strip()
        port = 993

    nickname = input("Nickname for this account (e.g. Work, Personal): ").strip()

    account = {
        "nickname": nickname,
        "email":    email_addr,
        "password": app_password,
        "host":     host,
        "port":     port,
    }

    accounts = load_accounts()
    accounts.append(account)
    save_accounts(accounts)
    print(f"  ✓ Account '{nickname}' added!\n")
    return account


# ──────────────────────────────────────────────
#  EMAIL HELPERS
# ──────────────────────────────────────────────

def decode_str(value):
    """Decode encoded email header strings (handles UTF-8, base64, etc.)."""
    if value is None:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            except Exception:
                decoded.append(part.decode("utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def get_body(msg):
    """Extract plain-text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition  = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                charset = part.get_content_charset() or "utf-8"
                try:
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                break
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return body.strip()


# ──────────────────────────────────────────────
#  CORE: FETCH LAST 10 EMAILS
# ──────────────────────────────────────────────

def fetch_recent_emails(account, count=10):
    """
    Connect to IMAP server, fetch the last `count` emails,
    return a list of dicts with subject, sender, date, and body.
    """
    print(f"\nConnecting to {account['host']} as {account['email']} ...")

    try:
        mail = imaplib.IMAP4_SSL(account["host"], account["port"])
        mail.login(account["email"], account["password"])
        print("  ✓ Login successful")
    except imaplib.IMAP4.error as e:
        print(f"  ✗ Login failed: {e}")
        print("  Tip: Make sure you're using an App Password, not your regular password.")
        return []

    mail.select("INBOX")

    # Get total message count, then fetch the last `count` emails
    status, data = mail.search(None, "ALL")
    mail_ids = data[0].split()

    if not mail_ids:
        print("  No emails found in inbox.")
        mail.logout()
        return []

    # Slice last `count` IDs
    recent_ids = mail_ids[-count:]
    recent_ids.reverse()   # newest first

    emails = []
    print(f"  Fetching last {len(recent_ids)} emails...\n")

    for uid in recent_ids:
        status, msg_data = mail.fetch(uid, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_str(msg.get("Subject", "(no subject)"))
        sender  = decode_str(msg.get("From",    "(unknown sender)"))
        date    = decode_str(msg.get("Date",    "(no date)"))
        body    = get_body(msg)

        emails.append({
            "subject": subject,
            "from":    sender,
            "date":    date,
            "body":    body,
        })

    mail.logout()
    return emails


def display_emails(emails, account_name):
    """Pretty-print fetched emails to the terminal."""
    if not emails:
        print("No emails to display.")
        return

    print(f"\n{'═' * 65}")
    print(f"  📬  {account_name}  —  Last {len(emails)} Emails")
    print(f"{'═' * 65}")

    for i, em in enumerate(emails, 1):
        print(f"\n[{i}] {em['subject']}")
        print(f"    From : {em['from']}")
        print(f"    Date : {em['date']}")
        # Show first 300 characters of body as preview
        preview = em["body"][:300].replace("\n", " ")
        if len(em["body"]) > 300:
            preview += "..."
        print(f"    Body : {preview}")
        print(f"    {'─' * 60}")


# ──────────────────────────────────────────────
#  MENU
# ──────────────────────────────────────────────

def choose_account(accounts):
    """Let user pick from saved accounts."""
    print("\n── Saved Accounts ───────────────────────────")
    for i, acc in enumerate(accounts, 1):
        print(f"  [{i}] {acc['nickname']}  ({acc['email']})")
    print(f"  [{len(accounts)+1}] Add a new account")
    print(f"  [0] Exit")

    choice = input("\nChoose an account: ").strip()

    if choice == "0":
        return None, False

    try:
        idx = int(choice) - 1
        if idx == len(accounts):          # "Add new account"
            return add_account(), True
        elif 0 <= idx < len(accounts):
            return accounts[idx], True
        else:
            print("Invalid choice.")
            return None, True
    except ValueError:
        print("Please enter a number.")
        return None, True


def main():
    print("╔══════════════════════════════════════════╗")
    print("║       📧  Email Reader  (Free IMAP)      ║")
    print("╚══════════════════════════════════════════╝")

    while True:
        accounts = load_accounts()

        if not accounts:
            print("\nNo accounts saved yet. Let's add your first one.")
            account = add_account()
        else:
            account, continue_loop = choose_account(accounts)
            if not continue_loop:
                print("\nGoodbye!")
                break
            if account is None:
                continue

        if account:
            emails = fetch_recent_emails(account, count=10)
            display_emails(emails, account["nickname"] or account["email"])

            input("\nPress Enter to go back to the menu...")


if __name__ == "__main__":
    main()

# Step 1 Email Display
# -------------------------------------------------------------------------------------
