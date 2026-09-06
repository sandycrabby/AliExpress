# AliExpress price monitor

Watch specific AliExpress products (solar panels, batteries, anything with a product link) and get a **Telegram message** when the price enters a target you set.

This repo is meant to be easy to run on a home computer or a cheap always-on box. It stores watches and price history in a local SQLite file. There is no public website to log into — you talk to a Telegram bot, and there is an optional local status page.

## What you get

- A watch list: product URL or ID, optional nickname, max price or min–max range, ship-to country
- Periodic price checks (default every 3 hours) using a headless browser (Playwright)
- Price history in SQLite
- Telegram commands to add, list, remove, and force-check watches
- Alerts that do **not** spam you on every check
- Docker Compose **or** a plain Python start path
- A mock fetch mode so tests do not depend on live AliExpress

## Requirements

- Docker (easiest) **or** Python 3.11+
- A Telegram account
- About ten minutes

## 1. Create a Telegram bot

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`.
3. Pick a name (anything) and a username that ends in `bot`, for example `my_solar_price_bot`.
4. BotFather replies with a **token** that looks like `123456:ABC-DEF...`. Keep it private.
5. Open your new bot in Telegram and tap **Start** (or send `/start`). You will do this again after the monitor is running.

Optional: to lock alerts to your chat even before the first `/start`, send any message to [@userinfobot](https://t.me/userinfobot) and copy your numeric **Id**. That is `TELEGRAM_CHAT_ID`.

## 2. Configure the app

In this folder:

```bash
cp .env.example .env
```

Edit `.env` and paste your token:

```env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
# Optional but recommended after the first /start:
# TELEGRAM_CHAT_ID=123456789

CHECK_INTERVAL=3h
SHIP_TO_COUNTRY=US
CURRENCY=USD
FETCH_MODE=playwright
```

Leave `FETCH_MODE=playwright` for real AliExpress prices. Use `mock` only for tests or a dry run.

## 3. Run it

### Option A — Docker Compose (recommended)

You need Docker Desktop (or Docker Engine + Compose plugin).

```bash
docker compose up --build -d
docker compose logs -f
```

The bot and the scheduler run in **one** container. SQLite is stored in `./data/monitor.db` so it survives restarts.

Status page (optional): [http://localhost:8080](http://localhost:8080)

Stop:

```bash
docker compose down
```

### Option B — Python on your machine

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # downloads the browser used for live fetches

python -m aliexpress_monitor
```

The process stays in the foreground: Telegram bot + scheduler + status page.

## 4. Talk to the bot

In Telegram, open **your** bot and send:

| Command | What it does |
| --- | --- |
| `/start` | Welcome, and bind alerts to this chat if `TELEGRAM_CHAT_ID` is empty |
| `/help` | Full command list |
| `/add <url> <max_price> [nickname]` | Watch a product |
| `/list` | Show watches and last prices |
| `/remove <id>` | Stop watching |
| `/setrange <id> <min> <max>` | Alert only inside a band |
| `/check` | Fetch every watch right now |
| `/check <id>` | Fetch one watch |
| `/history <id>` | Recent stored prices |
| `/reset <id>` | Allow the next in-range price to alert again |
| `/whoami` | Print this chat’s numeric id |

Examples:

```
/add https://www.aliexpress.com/item/1005001234567890.html 95 Solar panel 200W
/add 1005001234567890 40
/setrange 1 70 95
/check
```

When a check finds a price at or below your max (or inside the min–max range), you get a message with the nickname, current price, previous price if known, and the product link.

## How alerts avoid spam

- First time the price **enters** the target → alert
- Same item still in range on later checks → **no** extra alert
- Price **leaves** the range, then comes back → alert again
- Price is still in range but **drops further** by about 2% or $1 (configurable) → alert again
- `/reset <id>` or `/setrange` re-arms the next in-range alert

## Local CLI (no Telegram)

Useful to confirm the database and mock/live fetch before you involve Telegram:

```bash
python -m aliexpress_monitor add https://www.aliexpress.com/item/1005001111111111.html 95 Solar
python -m aliexpress_monitor list
python -m aliexpress_monitor check
python -m aliexpress_monitor history 1
python -m aliexpress_monitor remove 1
```

With `FETCH_MODE=mock` those commands read `tests/fixtures/mock_prices.json` instead of AliExpress.

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | (empty) | From @BotFather. Required for the bot. |
| `TELEGRAM_CHAT_ID` | (empty) | Owner chat. If empty, the first `/start` claims it. |
| `CHECK_INTERVAL` | `3h` | How often to check. `2h`, `90m`, or seconds. |
| `SHIP_TO_COUNTRY` | `US` | Two-letter country used for every check. |
| `CURRENCY` | `USD` | Currency cookie sent with the page load. |
| `DATABASE_PATH` | `./data/monitor.db` | SQLite file. |
| `FETCH_MODE` | `playwright` | `playwright` (live) or `mock` (fixtures). |
| `MOCK_PRICES_PATH` | `tests/fixtures/mock_prices.json` | Used when `FETCH_MODE=mock`. |
| `ALERT_DROP_PERCENT` | `2` | Re-alert if price falls this % after the last alert. |
| `ALERT_DROP_ABS` | `1` | Or falls by this amount in the listing currency. |
| `CHECK_DELAY_SECONDS` | `4` | Pause between items (be polite to AliExpress). |
| `STATUS_PORT` | `8080` | Local status page. Set `0` to disable. |
| `PLAYWRIGHT_HEADLESS` | `true` | Set `false` only when debugging on a desktop. |

Keep `SHIP_TO_COUNTRY` and `CURRENCY` **stable**. AliExpress shows different prices by destination. If those change, history is no longer comparable.

## Tests

Unit tests use the mock fetcher and never open AliExpress:

```bash
pip install -r requirements-dev.txt
pytest
```

GitHub Actions runs the same suite.

## How price checks work

1. The scheduler (or `/check`) loads each watch from SQLite.
2. In `playwright` mode, Chromium opens the product page with an `aep_usuc_f` cookie that pins locale, currency, and ship-to region.
3. The app reads `window.runParams` when present, then JSON-LD, then a few visible price nodes.
4. For listings with several SKUs it stores the **lowest** visible/SKU price (the “from” price).
5. The reading is appended to `price_history` with a UTC timestamp.
6. Alert rules run; Telegram is notified only when they say so.

`mock` mode skips the browser and reads a JSON file keyed by product id. That is what CI uses.

## Known limitations

- **Anti-bot.** AliExpress often serves a slider captcha or empty page to datacenter IPs. The monitor treats that as a failed check, logs it, and tells you on `/check`. It does not solve captchas. A home/residential connection works more often than a cloud VM.
- **Price variance.** The same listing can show different prices by ship-to country, currency, selected SKU, coupons, and A/B tests. Pin country/currency and treat the stored number as “lowest listed,” not a checkout guarantee.
- **Layout changes.** AliExpress changes markup. Playwright + `runParams` is more resilient than CSS-only scrapers, but it can still break. Failures are logged; history simply skips that run.
- **Not a shopping API.** There is no official public price API. This is best-effort scraping of public product pages.
- **One owner.** The bot is personal. The first `/start` (or `TELEGRAM_CHAT_ID`) is the only chat that can add watches.
- **No SMS, no browser extension, no full dashboard.** The status page is a read-only peek at the database.

If live fetches fail from a server, run it at home, or keep `FETCH_MODE=mock` while you verify Telegram commands.

## Project layout

```
aliexpress_monitor/   Application (bot, scheduler, fetchers, SQLite)
tests/                Unit tests + HTML/JSON fixtures
data/                 Created at runtime (monitor.db)
.env.example          Copy to .env
Dockerfile            Bot + scheduler + Chromium
docker-compose.yml    One-service stack
```

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| Bot never replies | Token wrong, or the process is not running. Check `docker compose logs`. |
| “This bot only talks to its owner” | `/start` from the chat you want, or set `TELEGRAM_CHAT_ID` from `/whoami`. |
| `/check` says captcha / no price | AliExpress blocked the browser. Retry later, run from a home IP, or inspect logs. |
| Status page will not open | Confirm `STATUS_PORT=8080` and `docker compose port monitor 8080`. |
| Want a fresh alert | `/reset <id>` then `/check`. |

Questions about a specific listing: run `/check <id>` and read the error text the bot sends. That is the same message written to the logs.
