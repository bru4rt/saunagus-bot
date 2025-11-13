# Saunagus Bot

Playwright-based automation that wakes shortly after midnight, opens EasyTable’s Islands Brygge gus-booking page, and keeps retrying every 30 minutes until it secures the latest available slot inside your lead-window. It fills your personal details, optionally waits for a confirmation email (via IMAP), and writes a `.last_booking` marker so it never double-books the same day.

## Features

- Midnight-triggered run with configurable offset (`MIDNIGHT_OFFSET_SEC`) and retry cadence (`RETRY_INTERVAL_MIN`).
- Guest count, lead days, contact info, and booking policy driven entirely from `.env`.
- Automatically selects the latest green calendar day and time slot, then fills *Navn / Mobile / Email / Kommentar* fields.
- Optional IMAP watcher (disabled by default) to confirm bookings via email.
- Saves Playwright traces and screenshots for troubleshooting.

## Quick Start

1. **Install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure `.env`**
   - Copy `.env.example` if you create one, or edit `.env` directly.
   - Set `BOOK_URL`, `FIRST_NAME`, `EMAIL`, `MOBILE`, etc.
   - Leave `DRY_RUN=true` while testing; switch to `false` when you want real bookings.
   - Optionally uncomment and fill the IMAP block to let the bot confirm receipt of booking emails.

3. **Run the bot**
   ```bash
   source .venv/bin/activate
   python saunagus_book.py
   ```
   Start it any time before midnight. It will sleep until `00:00 + MIDNIGHT_OFFSET_SEC`, then retry every `RETRY_INTERVAL_MIN` minutes until a booking succeeds. Use `run_saunagus.sh` if you prefer a single command (also handy for cron/launchd).

## Tips

- The bot records the date of the last successful submission in `.last_booking`. Delete this file if you need to force another booking attempt the same day.
- Traces + screenshots land in `trace.zip` and `final_<timestamp>.png`. Review them when adjusting selectors.
- For unattended nightly runs, schedule `run_saunagus.sh` via `cron` or macOS `launchd`.

## Troubleshooting

- **New UI changes**: inspect `trace.zip` after a failed run and update the selectors in `saunagus_book.py`.
- **IMAP unavailable**: keep the IMAP block commented; the bot will still exit with status 0 after submitting the booking.
- **GitHub repo**: standard git workflow (`git status`, `git add`, `git commit`, `git push`) keeps the automation versioned.

Contributions and tweaks for other EasyTable setups are welcome—fork the repo and adjust the selectors/policies as needed.
