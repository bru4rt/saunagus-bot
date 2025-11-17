import os, sys, re, time, asyncio, datetime as dt
from dotenv import load_dotenv
from imapclient import IMAPClient
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

load_dotenv()

# --- Config ---
BOOK_URL  = os.getenv("BOOK_URL")
LEAD_DAYS = int(os.getenv("LEAD_DAYS","7"))
POLICY    = os.getenv("POLICY","earliest").lower()
GUESTS    = int(os.getenv("GUESTS","1"))

FIRST_NAME = os.getenv("FIRST_NAME","")
LAST_NAME  = os.getenv("LAST_NAME","")
EMAIL      = os.getenv("EMAIL","")
MOBILE     = os.getenv("MOBILE","")
COMMENT    = os.getenv("COMMENT","")

IMAP_HOST  = os.getenv("IMAP_HOST","")
IMAP_USER  = os.getenv("IMAP_USER","")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD","")
IMAP_FROM  = os.getenv("IMAP_FROM_CONTAINS","")
IMAP_SUBJ  = os.getenv("IMAP_SUBJECT_CONTAINS","confirmation")
CONFIRMATION_TIMEOUT_MIN = int(os.getenv("CONFIRMATION_TIMEOUT_MIN","10"))

HEADLESS   = os.getenv("HEADLESS","true").lower() == "true"
MIDNIGHT_OFFSET_SEC = int(os.getenv("MIDNIGHT_OFFSET_SEC","15"))
WAIT_FOR_MIDNIGHT   = os.getenv("WAIT_FOR_MIDNIGHT","true").lower() == "true"
DRY_RUN    = os.getenv("DRY_RUN","false").lower() == "false"
LAST_BOOK_FILE = os.getenv("LAST_BOOK_FILE", ".last_booking")
RETRY_INTERVAL_MIN = int(os.getenv("RETRY_INTERVAL_MIN", "30"))

TARGET_DATE = (dt.date.today() + dt.timedelta(days=LEAD_DAYS))

def log(msg): print(dt.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)

def already_booked_today():
    try:
        with open(LAST_BOOK_FILE, "r", encoding="utf-8") as fh:
            recorded = fh.read().strip()
        if not recorded:
            return False
        recorded_date = dt.date.fromisoformat(recorded)
        return recorded_date == dt.date.today()
    except FileNotFoundError:
        return False
    except Exception as exc:
        log(f"⚠ Could not read '{LAST_BOOK_FILE}': {exc}")
        return False

def mark_booking_today():
    try:
        with open(LAST_BOOK_FILE, "w", encoding="utf-8") as fh:
            fh.write(dt.date.today().isoformat())
    except Exception as exc:
        log(f"⚠ Could not update '{LAST_BOOK_FILE}': {exc}")

async def advance_initial_steps(page):
    # Click through “Info / Guests / Date” tabs when present
    for _ in range(3):
        try:
            btn = page.get_by_role("button", name=re.compile(r"(next|continue|fortsæt|næste)", re.I))
            await btn.click(timeout=1500)
        except PwTimeout:
            break

# async def set_guests(page):
#     # Try +/- buttons or a visible number input
#     try:
#         # normalize to 1
#         for _ in range(4):
#             try:
#                 await page.get_by_role("button", name=re.compile(r"-")).click(timeout=700)
#             except PwTimeout:
#                 break
#         for _ in range(max(0, GUESTS-1)):
#             await page.get_by_role("button", name=re.compile(r"\+")).click(timeout=700)
#         log(f"Guests set to {GUESTS}")
#         for name in ["Next","Continue","Fortsæt","Næste"]:
#             try:
#                 await page.get_by_role("button", name=re.compile(name,re.I)).click(timeout=1200); break
#             except PwTimeout:
#                 continue
#     except PwTimeout:
#         log("Guests control not found; continuing.")

async def select_target_date(page):
    # Wait for calendar header like "november 2025"
    header = await page.get_by_text(re.compile(r"\w+\s+\d{4}", re.I)).first.inner_text()
    header = header.strip().lower()  # e.g. "november 2025"
    log(f"Calendar header: {header}")

    parts = header.split()
    if len(parts) < 2:
        raise RuntimeError(f"Unexpected calendar header: {header}")
    month_name, year_str = parts[0], parts[1]
    year = int(year_str)

    # Map Danish month names to numbers, fallback to English if needed
    months_da = {
        "januar": 1, "februar": 2, "marts": 3, "april": 4,
        "maj": 5, "juni": 6, "juli": 7, "august": 8,
        "september": 9, "oktober": 10, "november": 11, "december": 12
    }
    if month_name in months_da:
        month = months_da[month_name]
    else:
        # fallback for English header like "November 2025"
        month = dt.datetime.strptime(month_name.capitalize(), "%B").month

    today = dt.date.today()
    max_date = today + dt.timedelta(days=LEAD_DAYS)

    candidates = []  # (element, date)

    async def collect_span_days():
        nonlocal candidates
        day_cells = page.locator("#calendar span.day")
        count = await day_cells.count()
        if not count:
            return
        for idx in range(count):
            el = day_cells.nth(idx)
            classes = (await el.get_attribute("class") or "").split()
            if "av" not in classes:
                continue  # only consider available (green) days
            data_date = await el.get_attribute("data-date")
            target_date = None
            if data_date:
                try:
                    target_date = dt.datetime.strptime(data_date, "%d-%m-%Y").date()
                except ValueError:
                    target_date = None
            if target_date is None:
                # Fallback to visible number
                txt = (await el.inner_text() or "").strip()
                m = re.search(r"\b(\d{1,2})\b", txt)
                if not m:
                    continue
                day = int(m.group(1))
                try:
                    target_date = dt.date(year, month, day)
                except ValueError:
                    continue

            if target_date < today or target_date > max_date:
                continue
            candidates.append((el, target_date))

    await collect_span_days()

    # Fallback to generic role scanning for older markup
    if not candidates:
        for role in ["button", "gridcell"]:
            elems = await page.get_by_role(role).all()
            for el in elems:
                txt = ""
                try:
                    txt = (await el.inner_text() or "").strip()
                except:
                    pass
                if not txt:
                    try:
                        txt = (await el.get_attribute("aria-label") or "").strip()
                    except:
                        pass
                if not txt:
                    continue

                # Must contain a day number
                m = re.search(r"\b(\d{1,2})\b", txt)
                if not m:
                    continue
                day = int(m.group(1))

                # Build the date this circle represents
                try:
                    d = dt.date(year, month, day)
                except ValueError:
                    continue

                # Respect booking window
                if d < today or d > max_date:
                    continue

                # Skip clearly disabled days (no online booking)
                try:
                    if await el.is_disabled():
                        continue
                except:
                    pass

                candidates.append((el, d))

    if not candidates:
        log(f"No bookable days between {today} and {max_date}.")
        raise RuntimeError("No bookable dates found in calendar.")

    # Choose the furthest (latest) date within the allowed range
    el, chosen_date = max(candidates, key=lambda pair: pair[1])
    await el.click(timeout=1500)
    log(f"Selected calendar date {chosen_date}")

    # Proceed to time selection step
    for lab in ["Next","Continue","Fortsæt","Næste"]:
        try:
            await page.get_by_role("button", name=re.compile(lab, re.I)).click(timeout=1200)
            break
        except PwTimeout:
            continue

def pick_slot(candidates, policy):
    if not candidates: return None
    if policy == "earliest":
        return min(candidates, key=lambda c: c[2])
    if policy == "morning":
        mornings = [c for c in candidates if c[2] < 12*60]
        return min(mornings, key=lambda c: c[2]) if mornings else min(candidates, key=lambda c: c[2])
    if policy == "evening":
        evenings = [c for c in candidates if c[2] >= 16*60]
        return min(evenings, key=lambda c: c[2]) if evenings else max(candidates, key=lambda c: c[2])
    return min(candidates, key=lambda c: c[2])

async def select_time(page):
    log("Selecting time slot...")

    times_container = page.locator("#times")
    await times_container.wait_for(timeout=8000)

    candidates = []

    async def collect_span_times():
        nonlocal candidates
        span_times = times_container.locator("span.time")
        count = await span_times.count()
        if not count:
            return
        for idx in range(count):
            el = span_times.nth(idx)
            classes = (await el.get_attribute("class") or "")
            if any(flag in classes for flag in ("disabled", "waitinglist", "ua")):
                continue
            label = (await el.inner_text() or "").strip()
            if not label:
                continue
            minutes = None
            data_time = await el.get_attribute("data-time")
            if data_time and data_time.isdigit():
                minutes = int(data_time)
            else:
                m = re.search(r"(\d{1,2})[:.](\d{2})", label)
                if m:
                    minutes = int(m.group(1))*60 + int(m.group(2))
            if minutes is None:
                continue
            candidates.append((el, label, minutes))

    await collect_span_times()

    if not candidates:
        # Fallback to old-style buttons just in case the markup changes again
        time_btns = await page.get_by_role("button").all()
        labels = []
        for b in time_btns:
            try:
                labels.append((b, (await b.inner_text()) or ""))
            except:
                labels.append((b, ""))
        for btn, label in labels:
            if not re.search(r"\b\d{1,2}[:.]\d{2}\b", label):
                continue
            try:
                if await btn.is_disabled():
                    continue
            except:
                pass
            m = re.search(r"(\d{1,2})[:.](\d{2})", label)
            if not m:
                continue
            hh, mm = int(m.group(1)), int(m.group(2))
            candidates.append((btn, label.strip(), hh*60+mm))

    if not candidates:
        raise RuntimeError("No enabled time buttons discovered.")

    btn, label, _ = pick_slot(candidates, POLICY)
    await btn.click()
    log(f"Selected slot: {label}")

    for lab in ["Next","Continue","Fortsæt","Næste"]:
        try:
            await page.get_by_role("button", name=re.compile(lab,re.I)).click(timeout=1200)
            break
        except PwTimeout:
            continue

async def preordering(page):
    # Skip add-ons if present
    for name in ["Skip","Continue","Next","Fortsæt","Næste"]:
        try:
            await page.get_by_role("button", name=re.compile(name,re.I)).click(timeout=1000); break
        except PwTimeout:
            continue

async def fill_and_submit(page):
    log("Filling confirmation form...")

    # --- Step 1: wait for the confirmation form to appear ---
    # Instead of relying on text like "Bekræft booking" / "Bevestigen boeking",
    # we just wait for typical form controls: email input + textarea.
    try:
        await page.locator("input[type='email']").first.wait_for(timeout=10000)
        await page.locator("textarea").first.wait_for(timeout=10000)
        log("Detected confirmation form via email input + textarea.")
    except PwTimeout:
        # As a fallback, wait for ANY text input to exist
        try:
            await page.locator("input[type='text']").first.wait_for(timeout=10000)
            log("Fallback: detected confirmation form via generic text input.")
        except PwTimeout:
            raise RuntimeError("Could not find confirmation form inputs on the page.")

    # --- Step 2: locate relevant fields by type/position ---

    text_inputs  = page.locator("input[type='text']")
    tel_inputs   = page.locator("input[type='tel']")
    email_inputs = page.locator("input[type='email']")
    textareas    = page.locator("textarea")

    # Name / Naam: first text input
    try:
        if FIRST_NAME and await text_inputs.count() >= 1:
            await text_inputs.nth(0).fill(FIRST_NAME)
            log("Filled name field (first text input).")
    except Exception as e:
        log(f"⚠ Could not fill name field: {e}")

    # Mobile / Mobiel: prefer tel input, otherwise second text input
    try:
        if MOBILE:
            if await tel_inputs.count() >= 1:
                await tel_inputs.nth(0).fill(MOBILE)
                log("Filled mobile field (tel input).")
            elif await text_inputs.count() >= 2:
                await text_inputs.nth(1).fill(MOBILE)
                log("Filled mobile field (second text input fallback).")
            else:
                log("⚠ No clear mobile input found.")
    except Exception as e:
        log(f"⚠ Could not fill mobile field: {e}")

    # Email / E-mail: dedicated email input if present, else third text input
    try:
        if EMAIL:
            if await email_inputs.count() >= 1:
                await email_inputs.nth(0).fill(EMAIL)
                log("Filled email field (email input).")
            elif await text_inputs.count() >= 3:
                await text_inputs.nth(2).fill(EMAIL)
                log("Filled email field (third text input fallback).")
            else:
                log("⚠ No clear email input found.")
    except Exception as e:
        log(f"⚠ Could not fill email field: {e}")

    # Comment / Kommentar / Opmerking: first textarea
    try:
        if COMMENT and await textareas.count() >= 1:
            await textareas.nth(0).fill(COMMENT)
            log("Filled comment field (first textarea).")
    except Exception as e:
        log(f"⚠ Could not fill comment field: {e}")

    await page.wait_for_timeout(500)

    # --- Step 3: submit (or skip in DRY_RUN) ---

    if DRY_RUN:
        log("DRY_RUN is true – not clicking confirm button.")
        return False

    # Try various confirm button texts: Danish, English, Dutch
    confirm_variants = [
        r"Bekræft",      # Danish
        r"Confirm",      # English
        r"Book",         # generic / English
        r"Boek nu",      # Dutch
    ]

    clicked = False
    for txt in confirm_variants:
        try:
            await page.get_by_role("button", name=re.compile(txt, re.I)).click(timeout=4000)
            log(f"Clicked confirm button matching '{txt}'.")
            clicked = True
            break
        except PwTimeout:
            continue

    if not clicked:
        raise RuntimeError("Could not find any confirm button (Bekræft/Confirm/Book/Boek nu).")

    log("Submitted confirmation form; booking should now be in progress.")
    await page.wait_for_timeout(2000)
    return True


async def assert_booking_confirmation(page):
    # Give the page a brief moment to navigate / render the success message
    await page.wait_for_timeout(2000)

    success_patterns = [
        r"Tak for din booking",
        r"Tak for din reservation",
        r"Din reservation er bekræftet",
        r"Reservation bekræftet",
        r"Bekræftelse",
        r"Bedankt voor je reservering",
        r"Je reservering er bekr[aæ]ftet",
        r"Je reservering is bevestigd",
        r"Je boeking is bevestigd",
        r"Reservation confirmed",
    ]

    for pattern in success_patterns:
        try:
            await page.get_by_text(re.compile(pattern, re.I)).first.wait_for(timeout=2500)
            log(f"Detected booking confirmation text matching '{pattern}'.")
            return
        except PwTimeout:
            continue

    error_patterns = [
        r"Fejl",
        r"Error",
        r"Ugyldig",
        r"Udfyld",
        r"Indtast",
        r"Oeps",
        r"Sorry",
        r"Kan ikke",
    ]

    for pattern in error_patterns:
        try:
            candidate = page.get_by_text(re.compile(pattern, re.I)).first
            await candidate.wait_for(timeout=1500)
            msg = (await candidate.inner_text()) if candidate else pattern
            raise RuntimeError(f"Detected potential error message after submit: '{msg.strip()}'")
        except PwTimeout:
            continue

    screenshot = f"no_confirm_{int(time.time())}.png"
    await page.screenshot(path=screenshot, full_page=True)
    raise RuntimeError(f"Did not detect booking confirmation text; saved {screenshot}")


def wait_for_confirmation_email():
    if not (IMAP_HOST and IMAP_USER and IMAP_PASSWORD):
        log("IMAP not configured; skipping email wait.")
        return None
    deadline = time.time() + CONFIRMATION_TIMEOUT_MIN*60
    with IMAPClient(IMAP_HOST, ssl=True) as server:
        server.login(IMAP_USER, IMAP_PASSWORD)
        server.select_folder("INBOX")
        while time.time() < deadline:
            criteria = ['UNSEEN']
            if IMAP_FROM: criteria += [f'FROM "{IMAP_FROM}"']
            if IMAP_SUBJ: criteria += [f'SUBJECT "{IMAP_SUBJ}"']
            msgs = server.search(criteria)
            if msgs:
                log("Confirmation email detected.")
                return True
            time.sleep(10)
    log("No confirmation email within timeout.")
    return False

async def book_once():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = await context.new_page()

        submitted = False
        try:
            log(f"Opening {BOOK_URL}")
            await page.goto(BOOK_URL, wait_until="domcontentloaded", timeout=45000)

            await select_guest_count(page)   # Hvor mange bliver I?
            await select_target_date(page)   # pick latest green day within LEAD_DAYS
            await select_time(page)          # pick latest available time
            submitted = await fill_and_submit(page)      # fill form (+ click Bekræft if not DRY_RUN)
            if submitted:
                await assert_booking_confirmation(page)

            await page.screenshot(path=f"final_{int(time.time())}.png")
            log("Flow finished (or DRY_RUN).")
            return submitted
        finally:
            await context.tracing.stop(path="trace.zip")
            await context.close()
            await browser.close()


async def select_guest_count(page):
    guest_label = str(GUESTS)

    # Allow multiple translations for the question
    question_patterns = [
        r"Hvor mange bliver i",
        r"Hvor mange er i",
        r"How many",
        r"Combien",
        r"Hoeveel",
        r"Quantos",
    ]

    question_locator = None
    for pattern in question_patterns:
        locator = page.get_by_text(re.compile(pattern, re.I))
        try:
            await locator.wait_for(timeout=3000)
            question_locator = locator
            log(f"Detected guest question using pattern '{pattern}'.")
            break
        except PwTimeout:
            continue

    # 1) Try proper role=button first (future-proof if a11y is added later)
    try:
        await page.get_by_role(
            "button",
            name=re.compile(rf"^{guest_label}\s*$")
        ).click(timeout=1500)
        log(f"Selected guest count {guest_label} via role=button.")
        await page.wait_for_timeout(800)
        return
    except PwTimeout:
        log("Guest count not exposed as role=button; falling back to text search.")

    # 2) Fallback: click the first element with text after the prompt
    if question_locator:
        xpath = f"xpath=following::*[normalize-space()='{guest_label}'][1]"
        try:
            await question_locator.locator(xpath).click(timeout=3000)
            log(f"Selected guest count {guest_label} via text near question.")
            await page.wait_for_timeout(800)
            return
        except PwTimeout:
            pass

    # 3) Final fallback: search within the qty step container
    qty_container = page.locator("#stepQty")
    try:
        await qty_container.wait_for(timeout=6000)
        candidate = qty_container.locator(f"xpath=.//*[normalize-space()='{guest_label}'][1]")
        await candidate.click(timeout=3000)
        log(f"Selected guest count {guest_label} via #stepQty fallback.")
        await page.wait_for_timeout(800)
        return
    except PwTimeout:
        raise RuntimeError("Failed to select guest count – controls not found.")


async def wait_until_midnight_offset():
    now = dt.datetime.now()
    if now.hour != 0:
        next_midnight = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_s = (next_midnight - now).total_seconds() + MIDNIGHT_OFFSET_SEC
        log(f"Sleeping {int(sleep_s)}s until midnight+{MIDNIGHT_OFFSET_SEC}s…")
        await asyncio.sleep(sleep_s)
    else:
        seconds_since_midnight = now.minute * 60 + now.second + now.microsecond / 1_000_000
        if seconds_since_midnight < MIDNIGHT_OFFSET_SEC:
            sleep_s = MIDNIGHT_OFFSET_SEC - seconds_since_midnight
            log(f"Sleeping {int(sleep_s)}s to satisfy midnight offset…")
            await asyncio.sleep(sleep_s)
        else:
            log("Already past midnight offset; starting immediately.")

async def main():
    if not DRY_RUN and already_booked_today():
        log(f"Booking already recorded in '{LAST_BOOK_FILE}' for today; exiting.")
        sys.exit(0)

    if WAIT_FOR_MIDNIGHT:
        await wait_until_midnight_offset()
    else:
        log("WAIT_FOR_MIDNIGHT is false – starting immediately.")

    while True:
        try:
            submitted = await book_once()
            if DRY_RUN:
                log("DRY_RUN finished. Exiting 0.")
                sys.exit(0)
            if submitted:
                mark_booking_today()
                email_result = wait_for_confirmation_email()
                if email_result:
                    log("✅ Booking confirmed by email. Exit 0.")
                    sys.exit(0)
                elif email_result is False:
                    log("⚠️ No confirmation email detected. Assuming booking succeeded based on UI.")
                    sys.exit(0)
                else:
                    log("Email watcher disabled; treating UI success as final.")
                    sys.exit(0)
            else:
                log("No booking was submitted; retrying.")
        except Exception as e:
            log(f"❌ Error: {e}")

        if not DRY_RUN and already_booked_today():
            log(f"Detected booking marker file '{LAST_BOOK_FILE}' set externally; exiting.")
            sys.exit(0)

        log(f"Waiting {RETRY_INTERVAL_MIN} minutes before next attempt...")
        await asyncio.sleep(RETRY_INTERVAL_MIN * 60)

if __name__ == "__main__":
    asyncio.run(main())
