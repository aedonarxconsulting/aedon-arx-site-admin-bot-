# Aedon Arx Consulting — WhatsApp Bot

AI WhatsApp reply bot (Groq) that answers from the live Firestore `properties` data, with the old keyword replies as an automatic fallback, plus a Firestore new-lead greeter.

## Files
- `aedon_arx_bot.py` — Flask app: `/webhook` (Fonnte incoming messages), `/new-lead` (manual trigger)
- `lead_listener.py` — background worker: watches Firestore `leads` collection, auto-greets new leads
- `requirements.txt`, `Procfile` — deployment config
- `.env` — your secrets (already has the Fonnte token filled in) — **never commit this file**

## Setup steps

1. **Push to a private repo** (not public — `.env` is git-ignored but the service account JSON must never touch git history either way).
2. On your host (Render, free tier):
   - Create **one Web Service** from this repo — Procfile handles the start command (`gunicorn aedon_arx_bot:app --bind 0.0.0.0:$PORT --workers 1`).
   - `lead_listener.py` runs *inside this same web service* as a background thread on app startup (no separate paid worker needed) — this is why `--workers 1` matters: with more than one gunicorn worker process, the listener would start multiple times and send duplicate greetings.
   - Free web services sleep after ~15 min of no traffic. Set up **UptimeRobot** (or similar) to ping your service URL every 5 minutes to keep it awake 24/7 — this is what keeps the Firestore listener alive continuously without paying for a worker dyno.
3. Set these environment variables on the web service:
   - `FONNTE_TOKEN` = your Fonnte device token
   - `FIREBASE_CREDENTIALS_JSON` = paste the full service account JSON as one line
   - `GROQ_API_KEY` = your Groq API key (from console.groq.com). Without it the bot falls back to the old keyword replies.
   - `GROQ_MODEL` = optional, defaults to `llama-3.3-70b-versatile`
4. In Fonnte dashboard → Device → set the **webhook URL** to `https://<your-deployed-web-url>/webhook`, so incoming messages reach the bot.
5. Confirm the Fonnte device (`Aedonarxconsulting`) is connected (green dot) — you already scanned this.
6. Test:
   - Send "hi" to the connected WhatsApp number → should get the greeting.
   - Add a test document to the `leads` Firestore collection → should get an auto-greeting within seconds.

## Notes
- No AI/Groq/OpenAI key needed — pure keyword matching (`aedon_arx_bot.py` → `KEYWORDS` dict).
- `lead_listener.py` checks multiple possible phone field names (`phone`, `whatsapp`, `mobile`, etc.) so a field-naming mismatch in the CRM won't silently break greetings.
- If the Fonnte token or Firebase key is ever exposed publicly, revoke and regenerate immediately.
