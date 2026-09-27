"""
Aedon Arx Consulting — WhatsApp Auto-Reply Bot (Keyword-based, NO AI)
Powered by: Flask + Fonnte
Style: Direct keyword detection, no numbered menu shown to user.
"""

import os
import threading
import requests
from flask import Flask, request

app = Flask(__name__)

# ── Config (set these as environment variables when deploying) ──────────────
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN", "")
FONNTE_SEND_URL = "https://api.fonnte.com/send"

# ── Company Details (Aedon Arx Consulting) ───────────────────────────────────
COMPANY_NAME = "Aedon Arx Consulting"
PHONE = "+91 99539 13605"
EMAIL = "connect@aedonarxconsulting.com"
WEBSITE = "https://aedonarxconsulting.com"
OFFICE = "Gurugram, Haryana"
HOURS = "Open Now — Appointment Only"
CITIES = "Gurugram, Noida, Faridabad, Tiruppur"
WHATSAPP_LINK = "https://wa.me/919953913605"

# ── Reply Templates ───────────────────────────────────────────────────────
GREETING_REPLY = (
    f"🏠 *{COMPANY_NAME}*\n"
    f"Real Estate Consultants — Residential & Commercial (RERA Verified)\n\n"
    f"Aapka swagat hai! 🙏\n\n"
    f"Aap humse pooch sakte hain:\n"
    f"• Company details / contact\n"
    f"• Timing & location\n"
    f"• Properties & budget\n"
    f"• Website\n"
    f"• Ya seedha consultant se baat karna chahein\n\n"
    f"Bas apna sawaal likh dijiye 👇"
)

COMPANY_DETAILS_REPLY = (
    f"🏢 *{COMPANY_NAME}*\n\n"
    f"📞 Phone/WhatsApp: {PHONE}\n"
    f"📧 Email: {EMAIL}\n"
    f"🌐 Website: {WEBSITE}\n"
    f"📍 Head Office: {OFFICE}\n"
    f"🕐 Hours: {HOURS}\n"
    f"🗺️ Serving: {CITIES}\n\n"
    f"RERA Approved ✅"
)

TIMING_LOCATION_REPLY = (
    f"🕐 *Timing:* {HOURS}\n"
    f"📍 *Head Office:* {OFFICE}\n"
    f"🗺️ *Pan India presence, active in:* {CITIES}"
)

WEBSITE_REPLY = (
    f"🌐 Humari saari listings, properties aur details yahan dekhein:\n{WEBSITE}"
)

PROPERTY_REPLY = (
    f"🏡 Hum residential & commercial dono tarah ki verified properties offer karte hain "
    f"({CITIES}).\n\n"
    f"Live listings aur budget-wise filter ke liye website dekhein:\n{WEBSITE}\n\n"
    f"Ya seedha consultant se baat karne ke liye 'consultant' likhein."
)

CONSULTANT_REPLY = (
    f"👤 Zaroor! Hamara consultant aapse jaldi hi connect karega.\n\n"
    f"Turant baat karne ke liye seedha call/WhatsApp karein:\n"
    f"📞 {PHONE}\n"
    f"🔗 {WHATSAPP_LINK}"
)

NO_NAHI_REPLY = (
    f"Koi baat nahi! Agar kabhi bhi zaroorat ho, humse yahan sampark karein:\n\n"
    f"📞 {PHONE}\n"
    f"🌐 {WEBSITE}\n\n"
    f"Ya seedha consultant se baat karne ke liye 'consultant' likhein."
)

FALLBACK_REPLY = (
    f"Iske baare mein poori jaankari ke liye hamari website dekhein:\n{WEBSITE}\n\n"
    f"Ya seedha consultant se baat karne ke liye 'consultant' likhein, "
    f"ya call karein: {PHONE}"
)

# ── Keyword Map ───────────────────────────────────────────────────────────
KEYWORDS = {
    "greeting": ["hi", "hello", "hey", "namaste", "namaskar", "start"],
    "company": ["company", "detail", "details", "about", "info", "kaun"],
    "contact": ["contact", "number", "phone", "email", "call"],
    "timing": ["timing", "time", "location", "address", "office", "kaha", "kaha hai"],
    "website": ["website", "site", "link"],
    "property": ["property", "properties", "flat", "house", "plot", "budget",
                 "bhk", "residential", "commercial", "listing", "listings"],
    "consultant": ["consultant", "agent", "human", "talk to", "baat karo",
                   "baat karao", "real person", "staff"],
    "negative": ["no", "nahi", "nah", "nope", "na "],
}


def match_intent(text: str) -> str:
    t = f" {text.lower().strip()} "
    for intent, words in KEYWORDS.items():
        for w in words:
            if f" {w} " in t or t.strip() == w:
                return intent
    return "fallback"


def build_reply(text: str) -> str:
    intent = match_intent(text)
    return {
        "greeting": GREETING_REPLY,
        "company": COMPANY_DETAILS_REPLY,
        "contact": COMPANY_DETAILS_REPLY,
        "timing": TIMING_LOCATION_REPLY,
        "website": WEBSITE_REPLY,
        "property": PROPERTY_REPLY,
        "consultant": CONSULTANT_REPLY,
        "negative": NO_NAHI_REPLY,
        "fallback": FALLBACK_REPLY,
    }[intent]


def send_whatsapp_reply(target: str, message: str):
    """Send a reply back to the customer via Fonnte. Logs Fonnte's actual
    response so failures (invalid number, quota, bad token) are visible in
    the deploy logs instead of silently looking like a success."""
    headers = {"Authorization": FONNTE_TOKEN}
    data = {"target": target, "message": message}
    try:
        resp = requests.post(FONNTE_SEND_URL, headers=headers, data=data, timeout=15)
        print(f"[Fonnte send] target={target} status={resp.status_code} "
              f"response={resp.text[:300]}")
    except requests.RequestException as e:
        print(f"[Fonnte send error] target={target} error={e}")


@app.route("/new-lead", methods=["POST"])
def new_lead():
    """
    Called by the CRM (Firestore trigger / admin panel) whenever a new lead
    is created — from website form, Meta Ads, or manual staff add.
    Sends an immediate WhatsApp greeting to that lead.

    Expected JSON body: {"phone": "9199...", "name": "optional"}
    """
    payload = request.get_json(silent=True) or {}
    phone = payload.get("phone")
    name = (payload.get("name") or "").strip()

    if not phone:
        return {"status": "error", "message": "phone is required"}, 400

    greeting = GREETING_REPLY
    if name:
        greeting = f"Namaste {name} ji! 🙏\n\n" + GREETING_REPLY

    send_whatsapp_reply(phone, greeting)
    return {"status": "sent", "phone": phone}, 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Fonnte sends incoming WhatsApp messages here (POST). Fonnte also
    pings this URL with GET to verify it's reachable when you save the
    webhook setting, so GET must not 405."""
    if request.method == "GET":
        return {"status": "webhook is up"}, 200

    payload = request.form if request.form else request.get_json(silent=True) or {}

    sender = payload.get("sender") or payload.get("phone") or payload.get("from")
    message_text = payload.get("message") or payload.get("text") or ""

    if not sender or not message_text:
        return {"status": "ignored"}, 200

    reply = build_reply(message_text)
    send_whatsapp_reply(sender, reply)

    return {"status": "ok"}, 200


@app.route("/", methods=["GET"])
def health():
    return "Aedon Arx WhatsApp bot is running.", 200


def _maybe_start_lead_listener():
    """
    Starts the Firestore lead listener in-process (same web dyno) so we
    don't need a separate paid Background Worker service. The Firestore
    on_snapshot watch itself is non-blocking (Google's SDK runs it on its
    own background thread), so this just needs to be triggered once when
    the app boots.
    """
    has_creds = os.environ.get("FIREBASE_CREDENTIALS_JSON") or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    if not has_creds:
        print("[app] FIREBASE_CREDENTIALS_JSON not set — lead listener disabled.")
        return
    try:
        from lead_listener import start_listener
        start_listener()
        print("[app] Firestore lead listener started (in-process).")
    except Exception as e:
        print(f"[app] Could not start lead listener: {e}")


_maybe_start_lead_listener()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
