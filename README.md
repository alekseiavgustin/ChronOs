# Chronos — Weekly Scheduler

Chronos is built around a simple idea: you have a list of things you need to do, and you should be able to drag them straight onto your week and schedule them — no friction, no fuss. Start with your tasks on the right, drag them onto the calendar on the left, and your week plans itself.

A fully offline weekly planner that lives in a single HTML file.  
No accounts. No server. No dependencies. Just open and schedule.

**[→ Open Chronos](https://chronos.oneapp.dev)** &nbsp;·&nbsp; [GitHub Pages mirror](https://alekseiavgustin.github.io/ChronOs/)

---

## Features

- **Drag-and-drop scheduling** — drag task cards from the panel onto the calendar grid
- **Draw to create** — click and drag directly on the calendar to draw a new event
- **Recurring events** — weekly or biweekly, on specific days you choose
- **Biweekly W1 / W2 view** — toggle between alternating week groups
- **Resize events** — drag the bottom edge of any event to adjust duration
- **Conflict detection** — red outline when a drop would overlap an existing event
- **Lock & Done** — lock events so they can't be moved; mark events as done
- **Undo / Redo** — full history with Ctrl+Z / Ctrl+Y, up to 40 steps
- **Categories** — 6 built-in colour categories, fully editable, add custom ones
- **Stats tab** — hours by category, hours by day, daily target progress bar
- **Outline tab** — chronological text view of the week, click to scroll the calendar
- **Save / Load** — produces a portable base64 code; paste it back on any device to restore
- **Apple Calendar export** — `.ics` export with configurable date range (4 weeks → 1 year)
- **PDF / Print** — opens a clean, print-ready pop-up of the current week
- **Bulk import** — paste a comma-separated task list; live preview before committing
- **AI integration** — built-in prompt and schedule-sharing tab for use with Claude or any LLM
- **Draggable divider** — resize the calendar / task panel split to your liking
- **Fully offline** — the entire app is one `.html` file; no data leaves your browser

---

## Usage

**Online:** visit the link above — nothing to install.

**Offline / self-hosted:**
```
1. Download index.html
2. Open it in any modern browser
3. That's it
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `N` | New task |
| `L` | Bulk import |
| `T` | Jump to today |
| `← →` | Previous / next week |
| `1` / `2` | Switch W1 / W2 biweekly view |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `?` | Show shortcuts |
| `Dbl-click` event | Edit event |
| `Right-click` event | Context menu |

---

## Bulk Import Format

Click the **⋮** list button (or press `L`) and paste tasks in this format:

```
Name, duration, category, repeat, days
```

Examples:
```
Morning run, 45m, Health, weekly, Mon Wed Fri
Deep work, 2h, Work
Team sync, 30m, Work, biweekly, Mon Wed
Read, 1h 30m, Learning, weekly, Mon Tue Wed Thu Fri
```

- **Duration:** `45m` · `2h` · `1h 30m` · `90` (bare number = minutes)
- **Category:** Work · Personal · Health · Social · Learning · Other · or any custom name
- **Repeat:** `weekly` or `biweekly` followed by day names

---

## Save Format

The **💾 Save** button produces a Base64-encoded JSON blob. Paste it into **📂 Load** on any device to restore your full schedule including categories, events, tasks, and settings. Nothing is stored server-side — the code is entirely self-contained.

---

## Telegram Bot

A companion bot — **[@chronos_1bot](https://t.me/chronos_1bot)** — lets you paste a Chronos save code into Telegram and receive reminders before your events. See [`chronos_bot.py`](bot/chronos_bot.py) and [`SETUP.md`](bot/SETUP.md) to self-host your own instance.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| UI | Vanilla HTML + CSS + JavaScript — zero frameworks |
| Fonts | Instrument Serif · JetBrains Mono · DM Sans (Google Fonts) |
| Storage | None — all state is in-memory; export is manual |
| Build | None — single file, open directly |

---

## License

MIT — see [LICENSE](LICENSE).  
Free to use, modify, and self-host. Attribution appreciated.

---

## Author

**Aleksei Avgustin** — [Alekseiavgustin25@gmail.com](mailto:Alekseiavgustin25@gmail.com)  
Built with the assistance of Claude AI by Anthropic.
