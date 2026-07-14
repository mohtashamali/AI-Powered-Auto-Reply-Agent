# AI based Personal Automation Agent

One Python agent that reads messages across Instagram, Gmail, WhatsApp, and Twitter — detects what each person wants — and replies individually, in your voice.

---

## What it does

| You say | Agent does |
|---|---|
| `python main.py --platform instagram` | Reads every unread DM, detects intent, replies in your tone |
| `python main.py --platform gmail` | Clears inbox: replies to real emails, labels, flags urgent ones |
| `python main.py --platform whatsapp` | Answers customer messages via Twilio |
| `python main.py --platform twitter` | Replies to all mentions |
| `python main.py` | Runs all connected platforms at once |
| `python main.py --schedule` | Runs every 30 min automatically |
| `python main.py --command "reply to my Instagram DMs"` | Natural language command |

---

## Setup

### 1. Clone and install

```bash
git clone <your-repo>
cd personal-automation-agent
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

Edit `.env` with your credentials. You only need to fill in the platforms you use.

#### Anthropic (required)
```
ANTHROPIC_API_KEY=sk-ant-...
```
Get it from: https://console.anthropic.com

#### Your persona (required)
```
MY_NAME=Your Full Name
MY_PROFESSION=Entrepreneur / Creator / etc
MY_TONE=friendly, professional, concise
```

#### Instagram
```
APIFY_TOKEN=...       # from https://console.apify.com
IG_USERNAME=...
IG_PASSWORD=...
```
Instagram has no official DM API. Apify provides a legal scraper.
Get Apify token free at: https://console.apify.com

#### Gmail
```
GMAIL_CREDENTIALS_JSON=./gmail_credentials.json
```
1. Go to https://console.cloud.google.com
2. Create project → Enable Gmail API
3. Create OAuth 2.0 credentials → Download as `gmail_credentials.json`
4. First run will open a browser for you to authorise

#### WhatsApp
```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```
1. Sign up at https://twilio.com
2. Enable WhatsApp Sandbox
3. Point your Twilio webhook to `https://your-server.com/whatsapp/webhook`

#### Twitter/X
```
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
TWITTER_BEARER_TOKEN=...
```
From: https://developer.twitter.com/en/portal/dashboard
Needs at minimum "Read and Write" permissions.

---

### 3. Test without credentials

```bash
python test_brain.py
```

This tests the AI intent detection and reply generation with mock messages across all platforms.

---

### 4. First run (dry run — no messages sent)

```bash
python main.py --dry-run
```

This runs the full pipeline — fetches messages, detects intents, generates replies — but does NOT send anything. Check the logs to see what would have been sent.

---

### 5. Go live

```bash
python main.py --platform instagram    # Instagram only
python main.py --platform gmail        # Gmail only
python main.py                         # All platforms
```

---

## Run on a schedule

```bash
# Run every 30 minutes
python main.py --schedule

# Run every 15 minutes
python main.py --schedule --interval 15
```

To run as a background service (Linux/macOS):
```bash
nohup python main.py --schedule > logs/scheduler.log 2>&1 &
```

---

## Dashboard

```bash
python main.py --dashboard
```

Shows: total replied, skipped, by platform, by intent.

---

## Human review queue

Some messages are too complex for AI (e.g. legal issues, media enquiries, serious complaints). These go into a queue:

```bash
# See what needs your attention
python main.py --human-queue

# Mark item #5 as handled
python main.py --resolve 5
```

---

## Deploy to production (Railway / Render)

For the WhatsApp real-time webhook:

```bash
# install Railway CLI
railway login
railway init
railway up
```

Set all env vars in the Railway dashboard, then point your Twilio webhook URL to:
`https://your-app.up.railway.app/whatsapp/webhook`

To run the webhook server:
```bash
python -c "from platforms.whatsapp import create_webhook_app; app = create_webhook_app(); app.run(port=8080)"
```

---

## How replies are generated

Each message goes through two Claude API calls:

1. **Intent detection** — classifies: `collab_request | pricing_query | compliment | complaint | customer_support | spam | general_question | job_offer | media_request`
2. **Reply generation** — writes a personalised reply in your configured tone, in the sender's language

Spam and bot messages are automatically skipped. Messages requiring human judgment are queued for your review.

---

## File structure

```
personal-automation-agent/
├── main.py                    ← entry point, CLI
├── requirements.txt
├── .env.example
├── agents/
│   └── brain.py               ← Claude: intent + reply
├── platforms/
│   ├── instagram.py           ← Instagram DM connector
│   ├── gmail.py               ← Gmail connector
│   ├── whatsapp.py            ← WhatsApp/Twilio connector
│   └── twitter.py             ← Twitter/X connector
├── memory/
│   ├── memory.py              ← SQLite: tracks all replied messages
│   └── agent.db               ← created automatically
├── utils/
│   └── logger.py              ← logging setup
├── logs/                      ← daily log files
└── test_brain.py              ← test AI without credentials
```

---

## Extend to new platforms

Adding a new platform takes ~50 lines. Copy the pattern from any existing connector:

```python
# platforms/telegram.py
from agents.brain import process_message
from memory.memory import has_replied, mark_replied

PLATFORM = "telegram"

def fetch_messages(): ...   # get messages from Telegram Bot API
def send_reply(chat_id, text): ...  # send via Telegram API

def run_telegram_agent(dry_run=False):
    messages = fetch_messages()
    for msg in messages:
        if has_replied(PLATFORM, msg["id"]): continue
        result = process_message(msg["sender"], msg["text"], PLATFORM)
        if not result.skip:
            send_reply(msg["chat_id"], result.reply_text)
            mark_replied(PLATFORM, msg["id"], ...)
```

Then register it in `main.py`.
