"""Online payment helpers (Paystack).

Nothing here runs unless PAYSTACK_SECRET_KEY is set in your environment.
An order is only marked Paid after Paystack itself confirms the payment
through the verify API (never because a browser says so).

Flutterwave can be added the same way: create flutterwave_initialize(),
flutterwave_verify() and a webhook signature check, then call them from the
payment routes in app.py.
"""
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.paystack.co"


def secret_key():
    return (os.environ.get("PAYSTACK_SECRET_KEY") or "").strip()


def paystack_enabled():
    return bool(secret_key())


def _call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API_BASE + path, data=data, method=method,
        headers={"Authorization": "Bearer " + secret_key(),
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return None


def paystack_initialize(email, amount_naira, reference, callback_url):
    """Start a payment. Returns the Paystack checkout URL, or None on failure."""
    result = _call("POST", "/transaction/initialize", {
        "email": email, "amount": int(amount_naira) * 100,  # Paystack uses kobo
        "currency": "NGN", "reference": reference, "callback_url": callback_url})
    if result and result.get("status") and result.get("data"):
        return result["data"].get("authorization_url")
    return None


def paystack_verified(reference, expected_naira):
    """True only if Paystack confirms a successful NGN payment of the right amount."""
    result = _call("GET", "/transaction/verify/" + urllib.parse.quote(reference, safe=""))
    if not result or not result.get("status"):
        return False
    data = result.get("data") or {}
    return (data.get("status") == "success"
            and data.get("reference") == reference
            and data.get("currency") == "NGN"
            and int(data.get("amount", -1)) == int(expected_naira) * 100)


def valid_webhook_signature(raw_body, signature):
    """Paystack signs webhooks with HMAC-SHA512 using your secret key."""
    if not secret_key() or not signature:
        return False
    expected = hmac.new(secret_key().encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
