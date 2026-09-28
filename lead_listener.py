"""
Aedon Arx Consulting — Firestore Lead Listener
Watches the `leads` collection in real time. When a new lead document is
created (website form, Meta Ads, or manual CRM add), it sends ONE WhatsApp
greeting via Fonnte to that lead — never again after that, even across a
service restart, because the greeted state is stored on the lead doc itself
(`greeted: true`), not just in this process's memory.

This only affects leads created from the moment this listener is running —
it does not touch, re-check, or re-greet any lead that already existed
before this version was deployed.

Run this as a separate long-running process (a "worker" dyno/service),
alongside the Flask web app in aedon_arx_bot.py — or, as set up here,
in-process as a background thread started by aedon_arx_bot.py on boot.
"""

import os
import time
import json

import firebase_admin
from firebase_admin import credentials, firestore

from aedon_arx_bot import greeting_reply, send_whatsapp_reply, append_to_thread

# ── Firebase init ────────────────────────────────────────────────────────
cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

if not firebase_admin._apps:
    if cred_json:
        cred = credentials.Certificate(json.loads(cred_json))
    elif cred_path:
        cred = credentials.Certificate(cred_path)
    else:
        raise RuntimeError(
            "Set FIREBASE_CREDENTIALS_JSON (paste JSON content) or "
            "GOOGLE_APPLICATION_CREDENTIALS (file path) as an env var."
        )
    firebase_admin.initialize_app(cred)

db = firestore.client()

PHONE_FIELDS = ["phone", "whatsapp", "whatsappNumber", "mobile", "contactNumber", "number"]
NAME_FIELDS = ["name", "fullName", "customerName"]


def _extract(doc_data: dict, candidates: list):
    for field in candidates:
        value = doc_data.get(field)
        if value:
            return str(value).strip()
    return None


def _normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def on_lead_snapshot(col_snapshot, changes, read_time):
    for change in changes:
        if change.type.name != "ADDED":
            continue  # only fresh leads — edits/updates don't re-trigger

        doc = change.document
        data = doc.to_dict() or {}

        # Persistent guard: this field lives in Firestore, so a service
        # restart can never cause a repeat greeting for a lead already
        # greeted before the restart.
        if data.get("greeted") is True:
            continue

        phone_raw = _extract(data, PHONE_FIELDS)
        if not phone_raw:
            print(f"[lead-listener] Skipped {doc.id}: no phone field found "
                  f"(checked {PHONE_FIELDS}) — check the lead doc's field names.")
            continue

        phone = _normalize_phone(phone_raw)
        name = _extract(data, NAME_FIELDS)

        greeting = greeting_reply("hi")
        if name:
            greeting = f"Namaste {name} ji! \U0001F64F\n\n" + greeting

        send_whatsapp_reply(phone, greeting)
        append_to_thread(doc.reference, "bot", greeting)

        # Mark it greeted immediately so nothing can send it twice, even if
        # the process restarts a second later.
        try:
            doc.reference.update({"greeted": True})
        except Exception as e:
            print(f"[lead-listener] Could not set greeted flag on {doc.id}: {e}")

        print(f"[lead-listener] Greeted new lead {doc.id} -> {phone}")


def start_listener():
    leads_ref = db.collection("leads")
    leads_ref.on_snapshot(on_lead_snapshot)
    print("[lead-listener] Watching 'leads' collection for new leads...")


if __name__ == "__main__":
    start_listener()
    while True:
        time.sleep(3600)
