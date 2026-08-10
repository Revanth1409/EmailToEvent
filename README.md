<div align="center">

# 📧 Email To Event

**Smart Email Event Manager — powered by local AI**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat&logo=flask)](https://flask.palletsprojects.com)
[![Ollama](https://img.shields.io/badge/Ollama-llama3.2-white?style=flat)](https://ollama.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

*Reads your emails → Extracts events using AI → Reminds you before they happen*

[Features](#-features) · [Installation](#-installation) · [Usage](#-usage) · [Tech Stack](#-tech-stack) · [Contributing](#-contributing)

</div>

---

## 🎯 What is Email To Event?

Email To Event is a smart desktop app that reads your Gmail or institutional email, uses a **locally running AI model** to automatically find events, deadlines, meetings, and workshops — then organises them in a clean dashboard with reminders, Google Calendar integration, and personalised recommendations.

**Your emails never leave your computer.** All AI processing runs locally using Ollama.

---

## ✨ Features

| Feature | Description |
|---|---|
| 📬 **Email Reader** | Connects to any Gmail or IMAP email account |
| 🤖 **AI Event Extraction** | Uses llama3.2 locally to find events, dates, venues, deadlines |
| 🏷️ **Auto Categorisation** | Sorts events into Academics, Clubs, Placements, Wellness, Finance, Meetings |
| 🔴 **Smart Priority** | Detects urgent, important, and optional events automatically |
| 📊 **Live Dashboard** | 3-column view — inbox, events, and detail panel |
| 🔔 **In-app Notifications** | Bell icon alerts before events you're attending |
| 📅 **Google Calendar** | Adds events with 5-minute reminders to your phone |
| ✨ **Interest Learning** | Learns what you attend and recommends similar future events |
| 🖥️ **System Tray App** | Runs silently in the background on Windows |

---

## 🚀 Installation

### Prerequisites

Install these first (one time only):

| Tool | Download | Why |
|---|---|---|
| Python 3.10+ | [python.org](https://python.org) | Runs the backend |
| Ollama | [ollama.com](https://ollama.com) | Runs AI locally |
| Git (optional) | [git-scm.com](https://git-scm.com) | To clone the repo |

> ⚠️ When installing Python, make sure to check **"Add Python to PATH"**

---

### Step 1 — Download Email To Event

**Option A — Clone with Git:**
```bash
git clone https://github.com/Revanth1409/EmailToEvent.git
cd EmailToEvent
```

**Option B — Download ZIP:**
- Click **Code → Download ZIP** on this page
- Extract the folder

---

### Step 2 — Run the installer

Double-click **`install.bat`**

This automatically:
- Installs all Python packages
- Downloads the llama3.2 AI model (~2GB)
- Creates an **Email To Event** shortcut on your Desktop

---

### Step 3 — Google Calendar setup (optional)

Only needed if you want "Add to Calendar" to work:

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → Enable **Google Calendar API**
3. Create **OAuth 2.0 credentials** → Desktop App
4. Download `credentials.json` → place it in the project folder

---

### Step 4 — Get your Email App Password

Email To Event uses an **App Password**, not your regular Gmail password.

**For Gmail:**
1. Go to [myaccount.google.com](https://myaccount.google.com) → Security
2. Enable **2-Step Verification**
3. Search **"App passwords"** → create one named "EmailToEvent"
4. Copy the 16-character password shown

**For institutional email (IITM, college etc.):**
- Check if your college email is powered by Google — if yes, same steps above
- Otherwise ask your IT department for the IMAP server address

---

## 📖 Usage

**Launch the app:**
- Double-click **Email To Event** on your Desktop, or
- Run `python launcher.py` in the project folder

Your browser opens automatically at `http://localhost:5000`

**First time:**
1. Click **↓ Fetch** — enter your email and App Password when prompted
2. Email To Event reads your last 20 emails and extracts events
3. Review the events in the middle column
4. Click **✓ Will Attend** or **✕ Cannot Attend** on each event
5. Click **＋ Add to Calendar** to get a phone reminder 5 minutes before

**Daily use:**
- Open EmailToEvent → click Fetch → your new events appear automatically
- The 🔔 bell shows alerts for upcoming events you're attending
- The **✨ Your Interests** panel learns your preferences over time

---

## 🗂️ Project Structure

```
EmailToEvent/
├── app.py               # Flask backend — all API routes
├── calendar_helper.py   # Google Calendar integration
├── email_reader.py      # IMAP email reader
├── event_extractor.py   # Standalone event extractor (CLI version)
├── launcher.py          # Startup script — launches Ollama + Flask
├── tray.py              # Windows system tray app
├── install.bat          # One-click Windows installer
├── EmailToEvent.bat     # Terminal launcher (for debugging)
├── requirements.txt     # Python dependencies
├── static/
│   └── dashboard.html   # Frontend dashboard
├── .gitignore
└── README.md
```

**Auto-created on first run (not in repo):**
```
├── email_accounts.json  # Your saved email accounts
├── events.db            # Extracted events database
├── credentials.json     # Your Google OAuth file (you add this)
└── calendar_token.json  # Auto-generated after Google login
```

---

## 🛠️ Tech Stack

| Layer | Technology | Cost |
|---|---|---|
| AI Model | Ollama + llama3.2 (runs locally) | Free |
| Backend | Python + Flask | Free |
| Database | SQLite | Free |
| Email | IMAP (no API needed) | Free |
| Calendar | Google Calendar API | Free |
| Frontend | HTML + CSS + JavaScript | Free |

**Total cost to run: ₹0**

---

## 🔒 Privacy

- **All AI processing is local** — your emails never go to any cloud AI service
- `credentials.json`, `email_accounts.json`, and `events.db` are gitignored and never uploaded
- Your App Password is stored only on your own machine

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| Blank white page | Hard refresh with `Ctrl + Shift + R` |
| Ollama offline (red dot) | Run `ollama serve` in a terminal |
| Login failed | Use App Password, not your regular password |
| No events extracted | Some emails don't contain events — try fetching more |
| Calendar not working | Check `credentials.json` is in the project folder |
| Port already in use | Change `PORT = 5000` to `5001` in `launcher.py` |

---

## 🤝 Contributing

Pull requests are welcome! If you find a bug or want to add a feature:

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📋 Roadmap

- [ ] Mobile-friendly dashboard
- [ ] WhatsApp/Telegram notification support
- [ ] Multi-account switching in dashboard
- [ ] Export events to Excel
- [ ] Dark mode

---

## 👨‍💻 Author

**Revanth** — Student at IIT Madras

Built as a personal productivity tool for managing institute emails and events.

---

<div align="center">

If this helped you, consider giving it a ⭐ on GitHub!

</div>
