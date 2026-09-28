"""
Aedon Arx Consulting — WhatsApp Bot (Language-aware keyword flow, NO AI)
Powered by: Flask + Fonnte + Firestore

Handoff to a human is NOT keyword-triggered here. Staff flip a lead's
`ai_active` field to False from a button in the CRM — this bot just checks
that flag before replying and goes silent for that lead until it's
switched back on.
"""

import os
import re
import json
import requests
from datetime import datetime, timezone
from flask import Flask, request

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────
# Test token (MediSoft device 8407853708). Render env var FONNTE_TOKEN overrides this.
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN", "W4ZDb6dcnTGCAacJwRjp")
FONNTE_SEND_URL = "https://api.fonnte.com/send"

COMPANY_NAME = "Aedon Arx Consulting"
TAGLINE = "We Value Relationship"
WEBSITE = "https://aedonarxconsulting.com"
OFFICE_NUMBER = "+91 99539 13605"

PHONE_FIELDS = ["phone", "whatsapp", "whatsappNumber", "mobile", "contactNumber", "number"]
NAME_FIELDS = ["name", "fullName", "customerName"]

# ── Firebase (shared with lead_listener.py — one app instance) ─────────────
_db = None


def get_db():
    """Lazy Firestore client. Returns None if no credentials are configured
    (webhook still works for language/keyword replies, just skips the
    ai_active handoff lookup in that case)."""
    global _db
    if _db is not None:
        return _db
    if not firebase_admin._apps:
        cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        elif cred_path:
            cred = credentials.Certificate(cred_path)
        else:
            return None
        firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db


def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def find_lead_doc(phone: str):
    """Look up the Firestore lead doc for this phone, trying each known
    phone-field name (CRM schema isn't guaranteed to use one field name).
    Returns (doc_ref, doc_data) or (None, None)."""
    db = get_db()
    if db is None:
        return None, None
    leads_ref = db.collection("leads")
    for field in PHONE_FIELDS:
        try:
            for doc in leads_ref.where(field, "==", phone).limit(1).stream():
                return doc.reference, (doc.to_dict() or {})
        except Exception as e:
            print(f"[find_lead_doc] query error on field={field}: {e}")
    return None, None


def append_to_thread(doc_ref, sender: str, text: str):
    """Append one message to the lead's Firestore `thread` array so the CRM
    can show the full WhatsApp conversation, not just the first message.
    sender is 'lead' or 'bot' to match the shape the CRM already expects.
    Does nothing if the lead doc couldn't be found (e.g. an incoming
    message from a number with no matching lead record yet)."""
    if doc_ref is None:
        return
    try:
        doc_ref.update({
            "thread": firestore.ArrayUnion([{
                "from": sender,
                "text": text,
                "t": datetime.now(timezone.utc).isoformat(),
            }])
        })
    except Exception as e:
        print(f"[append_to_thread] failed for sender={sender}: {e}")


# ── Language detection ───────────────────────────────────────────────────
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

HINGLISH_WORDS = {
    "hai", "hain", "kya", "kaise", "mein", "chahiye", "kitna", "kitni",
    "kab", "kaha", "bhai", "ji", "nahi", "haan", "acha", "theek", "aap",
    "kar", "karo", "karna", "batao", "bata", "milega", "paisa", "rupaye",
    "dikhado",
}


def detect_language(text: str) -> str:
    """Returns 'hi' (Hinglish reply) or 'en' (English reply). Devanagari
    script is detected but replies still go out in Roman-script Hinglish,
    not Devanagari, per the current spec."""
    if DEVANAGARI_RE.search(text):
        return "hi"
    t = f" {text.lower().strip()} "
    for w in HINGLISH_WORDS:
        if f" {w} " in t:
            return "hi"
    return "en"


# ── Reply templates ───────────────────────────────────────────────────────
def greeting_reply(lang):
    if lang == "hi":
        return (f"Namaste! {COMPANY_NAME} mein aapka swagat hai — '{TAGLINE}'. "
                f"Aapki kaise madad kar sakte hain?")
    return (f"Hello! Welcome to {COMPANY_NAME} — '{TAGLINE}'. "
            f"How can we help you today?")


def thanks_reply(lang):
    if lang == "hi":
        return "You're welcome! Kuch aur chahiye ho to bataiyega."
    return "You're welcome! Let us know if you need anything else."


def bye_reply(lang):
    if lang == "hi":
        return f"{COMPANY_NAME} se sampark karne ke liye dhanyavaad. Aapka din shubh ho!"
    return f"Thank you for reaching out to {COMPANY_NAME}. Have a great day!"


def bot_check_reply(lang):
    if lang == "hi":
        return (f"Main {COMPANY_NAME} ka automated assistant hoon. Common sawalon ka "
                f"jawab turant de sakta hoon, specific chahiye ho to bata dijiye, "
                f"zaroorat padne par team se connect kar dunga.")
    return (f"I'm {COMPANY_NAME}'s automated assistant. I can instantly answer common "
            f"questions, and connect you with our team if you need something specific.")


def fallback_reply(lang):
    if lang == "hi":
        return (f"Iske liye aap hamari website dekh sakte hain: {WEBSITE}, "
                f"ya seedha office se baat karein: {OFFICE_NUMBER}.")
    return (f"For this, please check our website: {WEBSITE}, "
            f"or contact our office directly: {OFFICE_NUMBER}.")


_WEBSITE_TEMPLATES = {
    "hi": {
        "property": "Aap hamari saari properties yahan dekh sakte hain: {link}",
        "price": "Pricing project ke hisaab se alag hai, current rates website par dekhein: {link}",
        "amenities": "Amenities har project mein alag hote hain, poori details website par: {link}",
        "floorplan": "Floor plan aur brochure website se dekh ya download kar sakte hain: {link}",
        "location": "Saari project locations website par: {link}",
        "connectivity": "Connectivity details website par: {link}",
        "resale": "Resale/rental options website par: {link}",
        "commercial": "Commercial options website par: {link}",
        "possession": "Latest possession status website par: {link}",
        "size": "Exact size/area website par listed hai: {link}",
        "trust": "Hamare projects aur track record website par: {link}",
    },
    "en": {
        "property": "You can see all our properties here: {link}",
        "price": "Pricing varies by project, check current rates on our website: {link}",
        "amenities": "Amenities differ per project, full details on the website: {link}",
        "floorplan": "You can view or download the floor plan and brochure from the website: {link}",
        "location": "All project locations are listed on our website: {link}",
        "connectivity": "Connectivity details are on our website: {link}",
        "resale": "Resale/rental options are on our website: {link}",
        "commercial": "Commercial options are on our website: {link}",
        "possession": "Latest possession status is on our website: {link}",
        "size": "Exact size/area is listed on our website: {link}",
        "trust": "Our projects and track record are on our website: {link}",
    },
}

_OFFICE_TEMPLATES = {
    "hi": {
        "loan": "EMI/loan details ke liye office se baat karein: {office}",
        "visit": "Site visit schedule karne ke liye call/WhatsApp karein: {office}",
        "documents": "Legal/documentation details ke liye office se contact karein: {office}",
        "booking": "Booking process ke liye office se baat karein: {office}",
        "cancellation": "Cancellation/refund ke liye office se contact karein: {office}",
        "maintenance": "Maintenance charges ke liye office se poochein: {office}",
        "investment": "Investment potential office achhi tarah samjha denge: {office}",
        "vastu": "Facing/Vastu details ke liye office se confirm karein: {office}",
        "discount": "Best pricing ke liye seedha office se baat karein: {office}",
        "nri": "NRI process ke liye office se connect karein: {office}",
    },
    "en": {
        "loan": "For EMI/loan details, please speak with our office: {office}",
        "visit": "To schedule a site visit, please call/WhatsApp our office: {office}",
        "documents": "For legal/documentation details, contact our office: {office}",
        "booking": "For the booking process, please speak with our office: {office}",
        "cancellation": "For cancellation/refund, please contact our office: {office}",
        "maintenance": "For maintenance charges, please ask our office: {office}",
        "investment": "Our office can explain the investment potential in detail: {office}",
        "vastu": "For facing/Vastu details, please confirm with our office: {office}",
        "discount": "For the best pricing, please speak directly with our office: {office}",
        "nri": "For the NRI process, please connect with our office: {office}",
    },
}


def website_reply(lang, key):
    return _WEBSITE_TEMPLATES[lang][key].format(link=WEBSITE)


def office_reply(lang, key):
    return _OFFICE_TEMPLATES[lang][key].format(office=OFFICE_NUMBER)


# ── Intent keyword maps ───────────────────────────────────────────────────
GREETING_WORDS = ["hi", "hello", "hey", "namaste", "namaskar", "hlo",
                   "good morning", "good evening"]
THANKS_WORDS = ["thanks", "thank you", "thnx", "shukriya", "dhanyavad", "dhanyavaad"]
BYE_WORDS = ["bye", "goodbye", "alvida", "chalta hoon", "chalti hoon"]
BOT_CHECK_WORDS = ["are you a bot", "bot ho kya", "are you real", "robot ho"]

# NOTE: complaint/agent/human/handoff keywords are deliberately NOT here.
# Handoff is CRM-button-driven only (see find_lead_doc + ai_active check
# in webhook()) — the bot never decides this itself from message text.

WEBSITE_TOPICS = {
    "property": ["property", "properties", "flat", "plot", "apartment", "villa",
                 "2bhk", "3bhk", "project", "listing", "listings", "options available"],
    "price": ["price", "budget", "cost", "rate", "lakh", "crore", "kitna hai"],
    "amenities": ["amenities", "gym", "pool", "parking", "club", "garden"],
    "floorplan": ["floor plan", "brochure", "layout", "master plan"],
    "location": ["location", "area", "sector", "address"],
    "connectivity": ["connectivity", "metro", "nearby school", "nearby hospital"],
    "resale": ["resale", "rent", "rental", "lease"],
    "commercial": ["commercial", "office space", "shop", "showroom"],
    "possession": ["possession", "ready to move", "construction status"],
    "size": ["carpet area", "sq ft", "size"],
    "trust": ["why choose us", "reviews", "trust"],
}

OFFICE_TOPICS = {
    "loan": ["loan", "emi", "finance", "down payment", "interest rate"],
    "visit": ["site visit", "visit karna hai", "appointment", "schedule"],
    "documents": ["documents", "rera", "legal", "registry", "paperwork"],
    "booking": ["booking process", "token amount", "advance amount"],
    "cancellation": ["cancellation", "refund policy"],
    "maintenance": ["maintenance charges"],
    "investment": ["investment", "roi", "appreciation"],
    "vastu": ["vastu", "facing", "east facing", "west facing", "north facing", "south facing"],
    "discount": ["discount", "negotiate", "best price"],
    "nri": ["nri", "overseas buyer"],
}


def _contains_any(t, words):
    return any(w in t for w in words)


def match_topic(t):
    for key, words in WEBSITE_TOPICS.items():
        if _contains_any(t, words):
            return ("website", key)
    for key, words in OFFICE_TOPICS.items():
        if _contains_any(t, words):
            return ("office", key)
    return None


def build_reply(text: str) -> str:
    """Priority order: are-you-a-bot -> thanks/bye -> greeting -> topic
    intents -> fallback. (Handoff isn't decided here — see webhook().)"""
    lang = detect_language(text)
    t = f" {text.lower().strip()} "

    if _contains_any(t, BOT_CHECK_WORDS):
        return bot_check_reply(lang)
    if _contains_any(t, THANKS_WORDS):
        return thanks_reply(lang)
    if _contains_any(t, BYE_WORDS):
        return bye_reply(lang)
    if _contains_any(t, GREETING_WORDS):
        return greeting_reply(lang)

    topic = match_topic(t)
    if topic:
        kind, key = topic
        return website_reply(lang, key) if kind == "website" else office_reply(lang, key)

    return fallback_reply(lang)


def send_whatsapp_reply(target: str, message: str):
    """Send a reply back to the customer via Fonnte. Logs Fonnte's actual
    response so failures (invalid number, quota, bad token) are visible in
    the deploy logs instead of silently looking like a success."""
    headers = {"Authorization": FONNTE_TOKEN}
    data = {"target": target, "message": message, "countryCode": "91"}
    try:
        resp = requests.post(FONNTE_SEND_URL, headers=headers, data=data, timeout=15)
        print(f"[Fonnte send] target={target} status={resp.status_code} "
              f"response={resp.text[:300]}")
    except requests.RequestException as e:
        print(f"[Fonnte send error] target={target} error={e}")


@app.route("/new-lead", methods=["POST"])
def new_lead():
    payload = request.get_json(silent=True) or {}
    phone = payload.get("phone")
    name = (payload.get("name") or "").strip()

    if not phone:
        return {"status": "error", "message": "phone is required"}, 400

    greeting = greeting_reply("hi")
    if name:
        greeting = f"Namaste {name} ji! \U0001F64F\n\n" + greeting

    send_whatsapp_reply(phone, greeting)

    lead_ref, _ = find_lead_doc(normalize_phone(phone))
    append_to_thread(lead_ref, "bot", greeting)

    return {"status": "sent", "phone": phone}, 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return {"status": "webhook is up"}, 200

    payload = request.form if request.form else request.get_json(silent=True) or {}
    sender = payload.get("sender") or payload.get("phone") or payload.get("from")
    message_text = payload.get("message") or payload.get("text") or ""

    if not sender or not message_text:
        return {"status": "ignored"}, 200

    phone = normalize_phone(sender)
    lead_ref, lead_data = find_lead_doc(phone)

    # Log the lead's incoming message regardless of handoff state, so staff
    # can see everything the lead said even while the bot is paused.
    append_to_thread(lead_ref, "lead", message_text)

    # ── CRM-button handoff check ──────────────────────────────────────────
    # Staff toggle ai_active=False on a lead from a button in the CRM. The
    # bot only reads that flag here — it never sets it itself from keywords.
    if lead_data and lead_data.get("ai_active") is False:
        print(f"[webhook] ai_active=False for {phone} — staying silent (staff handling).")
        return {"status": "handoff_active"}, 200

    reply = build_reply(message_text)
    send_whatsapp_reply(sender, reply)
    append_to_thread(lead_ref, "bot", reply)

    return {"status": "ok"}, 200


@app.route("/", methods=["GET"])
def health():
    return "Aedon Arx WhatsApp bot is running.", 200


def _maybe_start_lead_listener():
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
