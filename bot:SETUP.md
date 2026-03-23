# Chronos Telegram Bot — Setup Guide

A personal schedule assistant that reads your Chronos save codes and pings you before events.
Completely free — runs on your own machine (or any free-tier server).

---

## What you need

- Python 3.9+ (check: `python3 --version`)
- A Telegram account
- Your computer / laptop left running (or a free server — see below)

---

## Step 1 — Create your Telegram bot (2 min)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. *Chronos Assistant*) and a username (e.g. `my_chronos_bot`)
4. BotFather gives you a token that looks like `123456789:AAFxxx...`
5. Copy it — you'll paste it into the script

---

## Step 2 — Install dependencies

```bash
pip install "python-telegram-bot[job-queue]" apscheduler
```

---

## Step 3 — Configure the script

Open `chronos_bot.py` and edit the two lines at the top:

```python
BOT_TOKEN = "123456789:AAFxxx..."   # paste your token here
TIMEZONE  = "Asia/Makassar"         # Bali (WITA). Change if needed.
```

**Common timezones:**
- Bali / Indonesia Central: `Asia/Makassar`
- Moscow: `Europe/Moscow`
- London: `Europe/London`
- New York: `America/New_York`
- Singapore: `Asia/Singapore`

---

## Step 4 — Run it

```bash
python3 chronos_bot.py
```

Leave the terminal open (or run it in the background — see below).
The bot is now live. Open Telegram, find your bot by its username, and send `/start`.

---

## Step 5 — Load your schedule

1. Open Chronos in your browser
2. Click **💾 Save** in the toolbar
3. Copy the code that appears
4. Paste it into the Telegram bot

The bot will confirm how many events and reminders were loaded.
**To update your schedule any time**, just paste a new save code.

---

## Commands

| Command | What it does |
|---------|-------------|
| `/today` | Events for today |
| `/tomorrow` | Events for tomorrow |
| `/week` | Next 7 days |
| `/next` | Your very next event and time until it |
| `/remind 15` | Set reminder X minutes before events (0 = disable early reminder) |
| `/status` | Show loaded schedule summary |
| `/help` | Command list |

---

## Keeping the bot running 24/7

The bot must keep running to send reminders.

### Option A — Background on your own machine (simplest)
```bash
# Mac / Linux — run in background, keep running after terminal closes
nohup python3 chronos_bot.py > bot.log 2>&1 &

# To stop it later:
pkill -f chronos_bot.py
```

### Option B — Free cloud server (best for always-on)
**Oracle Cloud Always Free** or **Railway.app free tier** both work.

**Railway (easiest):**
1. Create a free account at railway.app
2. New project → Deploy from GitHub (push your `chronos_bot.py` there)
3. Add a `requirements.txt`:
   ```
   python-telegram-bot[job-queue]
   apscheduler
   ```
4. Set `BOT_TOKEN` as an environment variable in Railway's dashboard
   (then change the script line to `BOT_TOKEN = os.environ["BOT_TOKEN"]`)
5. Deploy — it runs forever for free

### Option C — Raspberry Pi / home server
Just `python3 chronos_bot.py` in a `screen` or `tmux` session.

---

## Notes

- **Reminders survive schedule updates** — pasting a new code clears all old reminders and schedules fresh ones.
- **Recurring events** (weekly / biweekly) generate reminders for the next 30 days automatically. Re-paste your code after 30 days to extend.
- **Done events** (marked ✓ in Chronos) are skipped.
- **Timezone** — make sure `TIMEZONE` matches where you actually are. The bot uses your system time to calculate when to fire reminders.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run the pip install command again |
| Bot doesn't respond | Make sure the script is still running |
| "Invalid code" | Make sure you copied the *entire* save code from Chronos — no spaces |
| Reminders not firing | Check that your timezone is set correctly |
| Python 3.9 not found | `python3.9 --version` or install via `brew install python@3.11` |
