#!/usr/bin/env python3
"""
Chronos Telegram Bot
────────────────────
Personal schedule assistant powered by your Chronos save code.
Sends reminders before events, lets you query today/week/next event.

Setup:
  1. pip install "python-telegram-bot[job-queue]" apscheduler
  2. Talk to @BotFather on Telegram → /newbot → copy the token
  3. Set environment variables: BOT_TOKEN, TIMEZONE, ADMIN_CHAT_ID
  4. python chronos_bot.py
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo          # Python 3.9+

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ── CONFIG — all via environment variables ─────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
TIMEZONE       = os.environ.get("TIMEZONE", "Asia/Makassar")  # default = Bali WITA
ADMIN_CHAT_ID  = int(os.environ.get("ADMIN_CHAT_ID", "0"))
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_REMIND_MINS = 15

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# user_state[chat_id] = { schedule, remind_minutes, job_ids[] }
user_state: dict = {}
# Buffer for multi-part save codes (Telegram splits long messages)
code_buffer: dict = {}  # chat_id -> {"parts": [], "job": None}
stats = {"total_users": set(), "schedules_loaded": 0}
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# ═══════════════════════════════════════════════════════════════════════════
#  CHRONOS PARSING
# ═══════════════════════════════════════════════════════════════════════════

def parse_code(code: str) -> dict:
    """Decode a Chronos base64 save code → dict."""
    padded = code.strip() + "=" * (-len(code.strip()) % 4)
    raw = base64.b64decode(padded).decode("utf-8")
    return json.loads(raw)


def week_start_dt(ws_iso: str, tz: ZoneInfo) -> datetime:
    """Parse the ws ISO string (week-start Monday) → tz-aware datetime at 00:00."""
    dt = datetime.fromisoformat(ws_iso.replace("Z", "+00:00"))
    return dt.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)


def ev_start_min(ev: dict, day_idx: int) -> int:
    """Return startMin for a day, respecting per-day recPos overrides."""
    rp = ev.get("recPos") or {}
    return rp.get(str(day_idx), rp.get(day_idx, ev.get("startMin", 0)))


def occurrences(ev: dict, ws_dt: datetime, days_ahead: int = 30) -> list[tuple]:
    """
    Yield (start_dt, end_dt, ev) tuples for the next `days_ahead` days.
    ws_dt must be tz-aware (Monday of the base week in the save file).
    """
    tz   = ws_dt.tzinfo
    now  = datetime.now(tz)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today_midnight + timedelta(days=days_ahead)
    dur    = ev.get("dur", 60)
    rec    = ev.get("recurring", "")
    days   = ev.get("recDays") or [ev.get("day", 0)]
    bw_grp = ev.get("bwGroup", 1)
    out    = []

    if not rec:
        d   = ev.get("day", 0)
        sm  = ev_start_min(ev, d)
        edt = ws_dt + timedelta(days=d, minutes=sm)
        if today_midnight <= edt < cutoff:
            out.append((edt, edt + timedelta(minutes=dur), ev))

    elif rec == "weekly":
        wk = ws_dt
        while wk < cutoff:
            for d in days:
                sm  = ev_start_min(ev, d)
                edt = wk + timedelta(days=d, minutes=sm)
                if today_midnight <= edt < cutoff:
                    out.append((edt, edt + timedelta(minutes=dur), ev))
            wk += timedelta(weeks=1)

    elif rec == "biweekly":
        wk, wk_num = ws_dt, 0
        while wk < cutoff:
            grp = 1 if wk_num % 2 == 0 else 2
            if grp == bw_grp:
                for d in days:
                    sm  = ev_start_min(ev, d)
                    edt = wk + timedelta(days=d, minutes=sm)
                    if today_midnight <= edt < cutoff:
                        out.append((edt, edt + timedelta(minutes=dur), ev))
            wk    += timedelta(weeks=1)
            wk_num += 1

    return sorted(out, key=lambda x: x[0])


def all_upcoming(schedule: dict, days_ahead: int = 30) -> list[tuple]:
    """All upcoming (start_dt, end_dt, ev) for a schedule."""
    tz   = ZoneInfo(TIMEZONE)
    ws   = week_start_dt(schedule.get("ws", datetime.now(tz).isoformat()), tz)
    result = []
    for ev in schedule.get("events", []):
        if ev.get("done"):
            continue
        result.extend(occurrences(ev, ws, days_ahead))
    return sorted(result, key=lambda x: x[0])


# ═══════════════════════════════════════════════════════════════════════════
#  FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def fmt_dur(mins: int) -> str:
    h, m = divmod(mins, 60)
    if h and m:  return f"{h}h {m}m"
    if h:        return f"{h}h"
    return f"{m}m"


def fmt_ev(ev: dict, s: datetime, e: datetime) -> str:
    rec_icon  = " 🔄" if ev.get("recurring") else ""
    lock_icon = " 🔒" if ev.get("locked") else ""
    return (
        f"• {s.strftime('%H:%M')}–{e.strftime('%H:%M')} "
        f"*{ev.get('name','?')}*{rec_icon}{lock_icon} "
        f"_{ev.get('cat','')} · {fmt_dur(ev.get('dur',0))}_"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  REMINDER JOBS
# ═══════════════════════════════════════════════════════════════════════════

def clear_jobs(chat_id: int):
    for jid in user_state.get(chat_id, {}).get("job_ids", []):
        try:
            scheduler.remove_job(jid)
        except Exception:
            pass
    if chat_id in user_state:
        user_state[chat_id]["job_ids"] = []


async def _send(bot, chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as ex:
        log.warning("send failed: %s", ex)


def reschedule(app: Application, chat_id: int) -> int:
    """Clear old jobs and schedule fresh reminders. Returns count of reminder jobs."""
    ud = user_state.get(chat_id)
    if not ud or not ud.get("schedule"):
        return 0

    clear_jobs(chat_id)
    remind_mins  = ud.get("remind_minutes", DEFAULT_REMIND_MINS)
    now          = datetime.now(ZoneInfo(TIMEZONE))
    job_ids      = []
    remind_count = 0

    for s, e, ev in all_upcoming(ud["schedule"], days_ahead=30):
        name = ev.get("name", "Event")
        cat  = ev.get("cat", "")
        dur  = ev.get("dur", 60)
        tag  = f"{chat_id}_{s.isoformat()}_{name[:8]}"

        # ── pre-event reminder ────────────────────────────────────────────
        if remind_mins > 0:
            rdt = s - timedelta(minutes=remind_mins)
            if rdt > now:
                jid = f"pre_{tag}"
                txt = (
                    f"⏰ *In {remind_mins} min* — *{name}*\n"
                    f"🕐 {s.strftime('%H:%M')}–{e.strftime('%H:%M')} · {fmt_dur(dur)}\n"
                    f"📂 {cat}"
                )
                scheduler.add_job(
                    _send, DateTrigger(run_date=rdt),
                    args=[app.bot, chat_id, txt],
                    id=jid, replace_existing=True,
                )
                job_ids.append(jid)
                remind_count += 1

        # ── at-start notification ─────────────────────────────────────────
        if s > now:
            jid = f"now_{tag}"
            txt = (
                f"🚀 *Starting now — {name}*\n"
                f"⏱ Until {e.strftime('%H:%M')} ({fmt_dur(dur)})\n"
                f"📂 {cat}"
            )
            scheduler.add_job(
                _send, DateTrigger(run_date=s),
                args=[app.bot, chat_id, txt],
                id=jid, replace_existing=True,
            )
            job_ids.append(jid)

    ud["job_ids"] = job_ids
    log.info("Scheduled %d jobs for chat %d", len(job_ids), chat_id)
    return remind_count


# ═══════════════════════════════════════════════════════════════════════════
#  BOT COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

HELP_TEXT = """
👋 *Chronos Assistant*

I read your Chronos schedule and send reminders before events.

*Load / update schedule*
Just paste your Chronos save code (from the 💾 Save button).

*Commands*
/today      — Events today
/tomorrow   — Events tomorrow
/week       — Next 7 days
/next       — Your next upcoming event
/remind 15  — Set reminder lead-time in minutes (0 = disable)
/status     — Schedule summary
/timezone   — Show or change timezone
/help       — This message
""".strip()


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    user = update.effective_user
    user_state.setdefault(cid, {"schedule": None, "remind_minutes": DEFAULT_REMIND_MINS, "job_ids": []})
    stats["total_users"].add(cid)

    # Notify admin of new user
    if ADMIN_CHAT_ID and cid != ADMIN_CHAT_ID:
        try:
            name = user.username or user.first_name or str(cid)
            await ctx.bot.send_message(
                ADMIN_CHAT_ID,
                f"👤 New user: @{name} (`{cid}`)",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ud  = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("No schedule loaded yet — paste your Chronos save code!")
        return

    tz    = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()
    evts  = [(s, e, ev) for s, e, ev in all_upcoming(ud["schedule"], 1) if s.date() == today]

    if not evts:
        await update.message.reply_text(f"📭 Nothing scheduled for today ({today.strftime('%a %d %b')}).")
        return

    lines = [f"📅 *Today — {today.strftime('%A, %d %b')}*\n"]
    lines += [fmt_ev(ev, s, e) for s, e, ev in evts]
    lines.append(f"\n⏱ Total: {fmt_dur(sum(ev.get('dur',0) for _,_,ev in evts))}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_tomorrow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ud  = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("No schedule loaded yet — paste your Chronos save code!")
        return

    tz   = ZoneInfo(TIMEZONE)
    tmrw = (datetime.now(tz) + timedelta(days=1)).date()
    evts = [(s, e, ev) for s, e, ev in all_upcoming(ud["schedule"], 2) if s.date() == tmrw]

    if not evts:
        await update.message.reply_text(f"📭 Nothing scheduled for tomorrow ({tmrw.strftime('%a %d %b')}).")
        return

    lines = [f"📅 *Tomorrow — {tmrw.strftime('%A, %d %b')}*\n"]
    lines += [fmt_ev(ev, s, e) for s, e, ev in evts]
    lines.append(f"\n⏱ Total: {fmt_dur(sum(ev.get('dur',0) for _,_,ev in evts))}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ud  = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("No schedule loaded yet — paste your Chronos save code!")
        return

    tz    = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()
    evts  = [(s, e, ev) for s, e, ev in all_upcoming(ud["schedule"], 7)]

    if not evts:
        await update.message.reply_text("📭 Nothing in the next 7 days.")
        return

    lines   = ["📆 *Next 7 days*\n"]
    cur_day = None
    for s, e, ev in evts:
        d = s.date()
        if d != cur_day:
            cur_day = d
            if d == today:
                label = f"Today, {d.strftime('%d %b')}"
            elif d == today + timedelta(days=1):
                label = f"Tomorrow, {d.strftime('%d %b')}"
            else:
                label = d.strftime("%A, %d %b")
            lines.append(f"\n*{label}*")
        lines.append(fmt_ev(ev, s, e))

    total = sum(ev.get("dur", 0) for _, _, ev in evts)
    lines.append(f"\n⏱ Week total: {fmt_dur(total)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ud  = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("No schedule loaded yet — paste your Chronos save code!")
        return

    tz       = ZoneInfo(TIMEZONE)
    now      = datetime.now(tz)
    upcoming = [(s, e, ev) for s, e, ev in all_upcoming(ud["schedule"], 7) if s > now]

    if not upcoming:
        await update.message.reply_text("📭 No upcoming events in the next 7 days.")
        return

    s, e, ev  = upcoming[0]
    delta     = s - now
    hrs, rem  = divmod(int(delta.total_seconds()), 3600)
    mins_left = rem // 60

    if delta.days >= 1:
        when = f"in {delta.days}d {hrs % 24}h"
    elif hrs:
        when = f"in {hrs}h {mins_left}m"
    else:
        when = f"in {mins_left}m"

    text = (
        f"⏭ *Next event — {when}*\n\n"
        f"{fmt_ev(ev, s, e)}\n"
        f"📅 {s.strftime('%A, %d %b')}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    user_state.setdefault(cid, {"schedule": None, "remind_minutes": DEFAULT_REMIND_MINS, "job_ids": []})

    if not ctx.args:
        curr = user_state[cid].get("remind_minutes", DEFAULT_REMIND_MINS)
        await update.message.reply_text(
            f"⏰ Reminder lead-time: *{curr} min* before each event.\n"
            "Change with `/remind 10` (use 0 to disable early reminder).",
            parse_mode="Markdown",
        )
        return

    try:
        mins = int(ctx.args[0])
        assert 0 <= mins <= 120
    except (ValueError, AssertionError):
        await update.message.reply_text("Usage: `/remind 15`  (0–120 minutes)", parse_mode="Markdown")
        return

    user_state[cid]["remind_minutes"] = mins
    count = reschedule(ctx.application, cid) if user_state[cid].get("schedule") else 0

    if mins == 0:
        await update.message.reply_text(
            "✅ Early reminders *disabled* — you'll still get a ping exactly at start time.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"✅ Reminder lead-time set to *{mins} min*. {count} upcoming reminders rescheduled.",
            parse_mode="Markdown",
        )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    ud  = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("No schedule loaded. Paste your Chronos save code!")
        return

    sch    = ud["schedule"]
    tz     = ZoneInfo(TIMEZONE)
    ws_str = week_start_dt(sch.get("ws", datetime.now(tz).isoformat()), tz).strftime("%d %b %Y")

    text = (
        f"📋 *Schedule status*\n\n"
        f"*Project:* {sch.get('proj','—')}\n"
        f"*Base week:* {ws_str}\n"
        f"*Events:* {len(sch.get('events',[]))}\n"
        f"*Unscheduled tasks:* {len(sch.get('tasks',[]))}\n"
        f"*Reminder lead-time:* {ud.get('remind_minutes', DEFAULT_REMIND_MINS)} min\n"
        f"*Active jobs:* {len(ud.get('job_ids',[]))}\n"
        f"*Timezone:* {TIMEZONE}\n\n"
        "Paste a new Chronos code any time to update."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid != ADMIN_CHAT_ID:
        return  # silently ignore

    total_jobs = sum(len(u.get("job_ids", [])) for u in user_state.values())
    loaded     = sum(1 for u in user_state.values() if u.get("schedule"))

    text = (
        f"📊 *Chronos Bot — Admin Stats*\n\n"
        f"👥 Unique users: {len(stats['total_users'])}\n"
        f"📥 Schedules loaded: {stats['schedules_loaded']}\n"
        f"🟢 Active sessions: {len(user_state)}\n"
        f"📅 Sessions with schedule: {loaded}\n"
        f"🔔 Scheduled reminder jobs: {total_jobs}\n"
        f"🌐 Timezone: {TIMEZONE}\n\n"
        "Use /broadcast <message> to notify all users."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only: broadcast a message to all users who have ever loaded a schedule."""
    cid = update.effective_chat.id
    if cid != ADMIN_CHAT_ID:
        return

    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/broadcast Your message here`\n"
            "Sends to all users who have loaded a schedule.",
            parse_mode="Markdown",
        )
        return

    msg     = " ".join(ctx.args)
    targets = list(stats["total_users"])
    ok, fail = 0, 0

    for uid in targets:
        try:
            await ctx.bot.send_message(
                uid,
                f"📢 *Message from Chronos*\n\n{msg}",
                parse_mode="Markdown",
            )
            ok += 1
        except Exception:
            fail += 1

    await update.message.reply_text(
        f"📢 Broadcast sent\n✅ {ok} delivered  ·  ❌ {fail} failed",
        parse_mode="Markdown",
    )


async def cmd_timezone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global TIMEZONE
    cid = update.effective_chat.id

    if not ctx.args:
        now = datetime.now(ZoneInfo(TIMEZONE))
        await update.message.reply_text(
            f"🌐 Current timezone: *{TIMEZONE}*\n"
            f"🕐 Local time now: *{now.strftime('%H:%M, %a %d %b')}*\n\n"
            "Change with `/timezone Asia/Singapore`\n"
            "Other examples:\n"
            "`/timezone Asia/Makassar` — Bali\n"
            "`/timezone Asia/Singapore` — SGT\n"
            "`/timezone Europe/Moscow` — Moscow\n"
            "`/timezone Europe/London` — London\n"
            "`/timezone America/New_York` — New York",
            parse_mode="Markdown",
        )
        return

    tz_input = ctx.args[0].strip()
    try:
        ZoneInfo(tz_input)  # validates it
    except Exception:
        await update.message.reply_text(
            f"❌ Unknown timezone `{tz_input}`.\n"
            "Use a standard tz name like `Asia/Singapore` or `Europe/London`.\n"
            "Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
            parse_mode="Markdown",
        )
        return

    TIMEZONE = tz_input
    scheduler.configure(timezone=TIMEZONE)

    count = 0
    for uid in user_state:
        if user_state[uid].get("schedule"):
            reschedule(ctx.application, uid)
            count += 1

    now = datetime.now(ZoneInfo(TIMEZONE))
    await update.message.reply_text(
        f"✅ Timezone set to *{TIMEZONE}*\n"
        f"🕐 Local time now: *{now.strftime('%H:%M, %a %d %b')}*\n"
        f"🔔 Rescheduled reminders for {count} active user(s).",
        parse_mode="Markdown",
    )


# ═══════════════════════════════════════════════════════════════════════════
#  MULTI-PART CODE BUFFER
# ═══════════════════════════════════════════════════════════════════════════

async def try_parse_buffer(ctx: ContextTypes.DEFAULT_TYPE):
    """Called 3s after last code chunk — joins all parts and tries to parse."""
    cid = ctx.job.data["cid"]
    app = ctx.job.data["app"]
    buf = code_buffer.pop(cid, None)
    if not buf:
        return

    full_code = "".join(buf["parts"])
    try:
        sch = parse_code(full_code)
        if "events" not in sch and "tasks" not in sch:
            raise ValueError("missing keys")

        user_state.setdefault(cid, {"schedule": None, "remind_minutes": DEFAULT_REMIND_MINS, "job_ids": []})
        user_state[cid]["schedule"] = sch
        stats["total_users"].add(cid)
        stats["schedules_loaded"] += 1
        count = reschedule(app, cid)

        tz         = ZoneInfo(TIMEZONE)
        today      = datetime.now(tz).date()
        today_evts = sum(1 for s, _, _ in all_upcoming(sch, 1) if s.date() == today)
        week_evts  = len(all_upcoming(sch, 7))

        reply = (
            f"✅ *Schedule loaded!*\n\n"
            f"📁 *{sch.get('proj','My Schedule')}*\n"
            f"📅 {len(sch.get('events',[]))} events  ·  "
            f"{len(sch.get('tasks',[]))} unscheduled tasks\n"
            f"🔔 {count} reminders set "
            f"({user_state[cid]['remind_minutes']}min before + at start)\n\n"
        )
        if today_evts:
            reply += f"You have *{today_evts}* event(s) today → /today\n"
        reply += f"*{week_evts}* event(s) in the next 7 days → /week"
        await ctx.bot.send_message(cid, reply, parse_mode="Markdown")

    except Exception as ex:
        log.debug("Buffer parse failed (%d chars): %s", len(full_code), ex)
        await ctx.bot.send_message(
            cid,
            "❌ Couldn't read that code — make sure you copy the *entire* save code from Chronos.",
            parse_mode="Markdown",
        )


# ═══════════════════════════════════════════════════════════════════════════
#  GENERIC MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    text = update.message.text.strip()

    # Could be a chunk of a Chronos save code — buffer and assemble
    looks_like_code = len(text) > 10 and " " not in text and "\n" not in text

    if looks_like_code:
        if cid not in code_buffer:
            code_buffer[cid] = {"parts": [], "job": None}
        code_buffer[cid]["parts"].append(text)

        # Cancel previous timer if any
        old_job = code_buffer[cid].get("job")
        if old_job:
            try:
                old_job.schedule_removal()
            except Exception:
                pass

        # Wait 3s for more parts, then parse the assembled code
        job = ctx.application.job_queue.run_once(
            try_parse_buffer,
            when=3,
            data={"cid": cid, "app": ctx.application},
            name=f"codeparse_{cid}",
        )
        code_buffer[cid]["job"] = job
        return

    # Fallback
    ud = user_state.get(cid, {})
    if not ud.get("schedule"):
        await update.message.reply_text("Paste your Chronos save code to get started, or use /help.")
    else:
        await update.message.reply_text(
            "Try /today, /tomorrow, /week, /next — or paste a new Chronos code to update your schedule."
        )


# ═══════════════════════════════════════════════════════════════════════════
#  POST INIT
# ═══════════════════════════════════════════════════════════════════════════

async def post_init(app: Application):
    scheduler.start()
    asyncio.create_task(self_ping())
    log.info("Scheduler started")


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if not BOT_TOKEN:
        print("❌  BOT_TOKEN environment variable not set!")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("tomorrow",  cmd_tomorrow))
    app.add_handler(CommandHandler("week",      cmd_week))
    app.add_handler(CommandHandler("next",      cmd_next))
    app.add_handler(CommandHandler("remind",    cmd_remind))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("timezone",  cmd_timezone))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Chronos Bot running — timezone: %s", TIMEZONE)
  
    import threading
import asyncio
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass

port = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", port), Health).serve_forever(),
    daemon=True
).start()

async def self_ping():
    if not RENDER_URL:
        return
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.get(RENDER_URL, timeout=10)
                log.info("Self-ping OK")
            except Exception as ex:
                log.warning("Self-ping failed: %s", ex)
            await asyncio.sleep(600)  # every 10 minutes
  
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
