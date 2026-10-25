"""Pajealex Fashion Hub - Flask e-commerce app.

Stage 1: storefront, cart, checkout, orders, WhatsApp ordering.
"""
import hmac
import os
import re
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash
from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)

load_dotenv()

import payments  # noqa: E402  (needs .env loaded first)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(INSTANCE_DIR, "store.db")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or os.path.join(INSTANCE_DIR, "uploads")
for folder in (INSTANCE_DIR, os.path.dirname(DATABASE_PATH), UPLOAD_DIR):
    os.makedirs(folder, exist_ok=True)

CATEGORIES = ["Clothing", "Shoes", "Sneakers", "Ear Pods", "Accessories"]
SORT_OPTIONS = {
    "newest": ("Newest first", "created_at DESC, id DESC"),
    "price_asc": ("Price: low to high", "price ASC, id ASC"),
    "price_desc": ("Price: high to low", "price DESC, id ASC"),
    "name": ("Name: A to Z", "name COLLATE NOCASE ASC"),
}
BASE_PAYMENT_METHODS = {
    "whatsapp": "WhatsApp order (pay on delivery)",
    "cod": "Cash on delivery",
}


PAYSTACK_LABEL = "Pay online (Paystack)"


def available_payment_methods():
    methods = dict(BASE_PAYMENT_METHODS)
    if payments.paystack_enabled():
        methods["paystack"] = PAYSTACK_LABEL
    return methods


def env(name, default=""):
    return (os.environ.get(name) or default).strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=env("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)
app.config["PERMANENT_SESSION_LIFETIME"] = 8 * 60 * 60  # admin stays logged in for 8 hours
if env("BEHIND_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
if not os.environ.get("SECRET_KEY"):
    print("WARNING: SECRET_KEY is not set. Using a temporary key; carts and "
          "logins reset every restart. Set SECRET_KEY in your .env file.")

STORE = {
    "name": "Pajealex Fashion Hub",
    "whatsapp": re.sub(r"\D", "", env("WHATSAPP_NUMBER")),
    "email": env("STORE_EMAIL"),
    "phone": env("STORE_PHONE"),
    "address": env("STORE_ADDRESS"),
    "instagram": env("INSTAGRAM_URL"),
    "facebook": env("FACEBOOK_URL"),
    "tiktok": env("TIKTOK_URL"),
}

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    category TEXT NOT NULL,
    image TEXT NOT NULL DEFAULT 'placeholder.svg',
    featured INTEGER NOT NULL DEFAULT 0,
    best_seller INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT NOT NULL UNIQUE,
    customer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    payment_method TEXT NOT NULL,
    payment_status TEXT NOT NULL DEFAULT 'Unpaid',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER,
    product_name TEXT NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SAMPLE_PRODUCTS = [
    ("JBL Ear Pod",
     "Wireless earbuds with a charging case. Sample product: replace this "
     "text and photo from the admin area.",
     15000, 25, "Ear Pods", "sample-earpod.svg", 1, 1),
    ("Adidas Up & Down Complete",
     "Matching top and bottom set for everyday wear. Sample product: replace "
     "this text and photo from the admin area.",
     30000, 15, "Clothing", "sample-adidas.svg", 1, 1),
    ("Men's Native Wear Up & Down",
     "Two-piece native outfit for occasions and everyday style. Sample "
     "product: replace this text and photo from the admin area.",
     40000, 10, "Clothing", "sample-native.svg", 1, 0),
]


def get_db():
    if "db" not in g:
        # isolation_level=None: we control transactions ourselves (BEGIN/COMMIT).
        g.db = sqlite3.connect(DATABASE_PATH, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO products (name, description, price, stock, category, "
            "image, featured, best_seller) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            SAMPLE_PRODUCTS,
        )


with app.app_context():
    init_db()

# --------------------------------------------------------------------------
# Security helpers (CSRF) and template helpers
# --------------------------------------------------------------------------


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def verify_csrf():
    if request.endpoint == "payment_webhook":
        return  # protected by Paystack's signature instead
    if request.method == "POST":
        sent = (request.form.get("_csrf") or "").encode()
        expected = (session.get("_csrf") or "").encode()
        if not sent or not expected or not hmac.compare_digest(sent, expected):
            abort(400)


@app.template_filter("naira")
def naira(value):
    try:
        return "\u20a6{:,}".format(int(value))
    except (TypeError, ValueError):
        return "\u20a60"


@app.template_filter("pretty_date")
def pretty_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return value or ""


def product_image(name):
    """Static sample images first, then photos uploaded by the admin."""
    name = os.path.basename(name or "placeholder.svg")
    if os.path.exists(os.path.join(app.static_folder, "images", name)):
        return url_for("static", filename="images/" + name)
    if os.path.exists(os.path.join(UPLOAD_DIR, name)):
        return url_for("media", filename=name)
    return url_for("static", filename="images/placeholder.svg")


app.jinja_env.globals.update(csrf_token=csrf_token, product_image=product_image)


@app.route("/media/<path:filename>")
def media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_next(default_endpoint):
    """Only redirect to paths on this website (blocks open redirects)."""
    target = request.form.get("next") or ""
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for(default_endpoint)


def get_product(product_id):
    if product_id is None:
        return None
    return get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


# --------------------------------------------------------------------------
# Cart (stored in the signed session cookie, so it survives page refreshes)
# --------------------------------------------------------------------------


def read_cart():
    clean = {}
    raw = session.get("cart", {})
    if not isinstance(raw, dict):
        return clean
    for key, value in raw.items():
        pid, qty = to_int(key), to_int(value)
        if pid is not None and qty is not None and qty > 0:
            clean[pid] = qty
    return clean


def save_cart(cart):
    session["cart"] = {str(pid): qty for pid, qty in cart.items()}


def cart_lines():
    """Return (lines, total). Prices always come from the database."""
    cart = read_cart()
    if not cart:
        return [], 0
    ids = list(cart)
    marks = ",".join("?" * len(ids))  # only "?" characters are inserted here
    rows = get_db().execute(f"SELECT * FROM products WHERE id IN ({marks})", ids).fetchall()
    lines, total = [], 0
    for row in rows:
        qty = cart[row["id"]]
        subtotal = row["price"] * qty
        total += subtotal
        lines.append({"product": row, "qty": qty, "subtotal": subtotal,
                      "over_stock": qty > row["stock"]})
    lines.sort(key=lambda line: line["product"]["name"].lower())
    return lines, total


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def inject_globals():
    return {"store": STORE, "categories": CATEGORIES,
            "cart_count": sum(read_cart().values()),
            "current_year": datetime.now().year}


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------


@app.route("/")
def index():
    db = get_db()
    featured = db.execute("SELECT * FROM products WHERE featured = 1 ORDER BY id DESC LIMIT 8").fetchall()
    new_arrivals = db.execute("SELECT * FROM products ORDER BY created_at DESC, id DESC LIMIT 4").fetchall()
    best_sellers = db.execute("SELECT * FROM products WHERE best_seller = 1 ORDER BY id DESC LIMIT 4").fetchall()
    counts = {row["category"]: row["n"] for row in
              db.execute("SELECT category, COUNT(*) AS n FROM products GROUP BY category")}
    return render_template("index.html", featured=featured, new_arrivals=new_arrivals,
                           best_sellers=best_sellers, counts=counts)


@app.route("/shop")
def shop():
    q = (request.args.get("q") or "").strip()[:80]
    category = request.args.get("category") or ""
    sort = request.args.get("sort") or "newest"
    if category not in CATEGORIES:
        category = ""
    if sort not in SORT_OPTIONS:
        sort = "newest"
    sql, params = "SELECT * FROM products WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY " + SORT_OPTIONS[sort][1]  # value comes from our own whitelist
    products = get_db().execute(sql, params).fetchall()
    return render_template("shop.html", products=products, q=q, category=category,
                           sort=sort, sort_options=SORT_OPTIONS)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)
    related = get_db().execute(
        "SELECT * FROM products WHERE category = ? AND id != ? ORDER BY id DESC LIMIT 4",
        (product["category"], product_id)).fetchall()
    in_cart = read_cart().get(product_id, 0)
    return render_template("product_detail.html", product=product, related=related, in_cart=in_cart)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/newsletter")
def newsletter():
    email = (request.form.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 120:
        flash("Please enter a valid email address.", "error")
    else:
        get_db().execute("INSERT OR IGNORE INTO subscribers (email) VALUES (?)", (email,))
        flash("Thanks for subscribing. We will keep you posted.", "success")
    return redirect(url_for("index") + "#newsletter")


# --------------------------------------------------------------------------
# Cart routes
# --------------------------------------------------------------------------


@app.route("/cart")
def cart():
    lines, total = cart_lines()
    return render_template("cart.html", lines=lines, total=total,
                           has_problem=any(line["over_stock"] for line in lines))


@app.post("/cart/add")
def cart_add():
    product = get_product(to_int(request.form.get("product_id")))
    if product is None:
        flash("That product could not be found.", "error")
        return redirect(url_for("shop"))
    qty = to_int(request.form.get("quantity"), 1)
    qty = 1 if qty is None or qty < 1 else min(qty, 99)
    cart_data = read_cart()
    current = cart_data.get(product["id"], 0)
    if product["stock"] <= 0:
        flash(f"{product['name']} is sold out.", "error")
    elif current + qty > product["stock"]:
        flash(f"Only {product['stock']} of {product['name']} in stock "
              f"({current} already in your cart).", "error")
    else:
        cart_data[product["id"]] = current + qty
        save_cart(cart_data)
        flash(f"{product['name']} added to your cart.", "success")
    return redirect(safe_next("shop"))


@app.post("/cart/update")
def cart_update():
    pid = to_int(request.form.get("product_id"))
    cart_data = read_cart()
    product = get_product(pid)
    if pid not in cart_data or product is None:
        cart_data.pop(pid, None)
        save_cart(cart_data)
        return redirect(url_for("cart"))
    qty = cart_data[pid]
    action = request.form.get("action")
    if action == "inc":
        qty += 1
    elif action == "dec":
        qty -= 1
    elif action == "set":
        qty = to_int(request.form.get("quantity"), qty)
    if qty < 1:
        cart_data.pop(pid)
        flash(f"{product['name']} removed from your cart.", "info")
    elif qty > product["stock"]:
        if product["stock"] <= 0:
            cart_data.pop(pid)
            flash(f"{product['name']} is sold out and was removed.", "error")
        else:
            cart_data[pid] = product["stock"]
            flash(f"Only {product['stock']} of {product['name']} in stock.", "error")
    else:
        cart_data[pid] = qty
    save_cart(cart_data)
    return redirect(url_for("cart"))


@app.post("/cart/remove")
def cart_remove():
    pid = to_int(request.form.get("product_id"))
    cart_data = read_cart()
    if cart_data.pop(pid, None) is not None:
        flash("Item removed from your cart.", "info")
    save_cart(cart_data)
    return redirect(url_for("cart"))


# --------------------------------------------------------------------------
# Checkout and orders
# --------------------------------------------------------------------------
PHONE_RE = re.compile(r"^\+?\d{10,15}$")


def validate_checkout(form):
    values = {
        "customer_name": " ".join((form.get("customer_name") or "").split()),
        "phone": re.sub(r"[\s\-()]", "", form.get("phone") or ""),
        "address": (form.get("address") or "").strip(),
        "email": (form.get("email") or "").strip().lower(),
        "notes": (form.get("notes") or "").strip(),
        "payment_method": form.get("payment_method") or "whatsapp",
    }
    errors = {}
    if len(values["customer_name"]) < 2 or len(values["customer_name"]) > 80:
        errors["customer_name"] = "Enter your full name (2 to 80 characters)."
    if not PHONE_RE.match(values["phone"]):
        errors["phone"] = "Enter a valid phone number, for example 08012345678."
    if len(values["address"]) < 10 or len(values["address"]) > 300:
        errors["address"] = "Enter your full delivery address (10 to 300 characters)."
    if values["email"] and (not EMAIL_RE.match(values["email"]) or len(values["email"]) > 120):
        errors["email"] = "That email address does not look right. Leave it blank if you prefer."
    if values["payment_method"] == "paystack" and not values["email"]:
        errors["email"] = "Email is required for online payment."
    if len(values["notes"]) > 500:
        errors["notes"] = "Order notes can be at most 500 characters."
    if values["payment_method"] not in available_payment_methods():
        errors["payment_method"] = "Choose a payment option."
    return values, errors


def new_order_number(db):
    while True:
        number = f"PFH-{datetime.now():%y%m%d}-{secrets.token_hex(3).upper()}"
        if not db.execute("SELECT 1 FROM orders WHERE order_number = ?", (number,)).fetchone():
            return number


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    lines, total = cart_lines()
    if not lines:
        flash("Your cart is empty. Add something first.", "info")
        return redirect(url_for("shop"))
    if request.method == "GET":
        return render_template("checkout.html", lines=lines, total=total, values={},
                               errors={}, payment_methods=available_payment_methods())

    values, errors = validate_checkout(request.form)
    if errors:
        return render_template("checkout.html", lines=lines, total=total, values=values,
                               errors=errors, payment_methods=available_payment_methods()), 400

    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        lines, total = cart_lines()  # re-read inside the transaction
        if not lines:
            raise ValueError("Your cart is empty.")
        for line in lines:
            if line["qty"] > line["product"]["stock"]:
                raise ValueError(f"Sorry, only {line['product']['stock']} of "
                                 f"{line['product']['name']} left in stock.")
        order_number = new_order_number(db)
        cur = db.execute(
            "INSERT INTO orders (order_number, customer_name, phone, email, address, "
            "notes, total, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (order_number, values["customer_name"], values["phone"], values["email"],
             values["address"], values["notes"], total,
             available_payment_methods()[values["payment_method"]]))
        order_id = cur.lastrowid
        for line in lines:
            p = line["product"]
            db.execute("INSERT INTO order_items (order_id, product_id, product_name, "
                       "unit_price, quantity) VALUES (?, ?, ?, ?, ?)",
                       (order_id, p["id"], p["name"], p["price"], line["qty"]))
            done = db.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                              (line["qty"], p["id"], line["qty"]))
            if done.rowcount != 1:
                raise ValueError(f"Sorry, {p['name']} just ran out of stock.")
        db.execute("COMMIT")
    except ValueError as exc:
        db.execute("ROLLBACK")
        flash(str(exc), "error")
        return redirect(url_for("cart"))
    except Exception:
        db.execute("ROLLBACK")
        app.logger.exception("Checkout failed")
        flash("Something went wrong while saving your order. Please try again.", "error")
        return redirect(url_for("checkout"))

    session.pop("cart", None)
    session["my_orders"] = (session.get("my_orders", []) + [order_number])[-20:]
    if values["payment_method"] == "paystack":
        pay_url = start_online_payment(order_number, values["email"], total)
        if pay_url:
            return redirect(pay_url)
        flash("We could not open the online payment page. Your order is saved; "
              "tap Pay online to try again, or pay on delivery.", "error")
    return redirect(url_for("order_success", order_number=order_number))


def start_online_payment(order_number, email, total):
    return payments.paystack_initialize(
        email, total, order_number, url_for("payment_callback", _external=True))


def whatsapp_link(order, items):
    if not STORE["whatsapp"]:
        return ""
    lines = [f"Hello {STORE['name']}, I just placed order {order['order_number']}.", "", "Items:"]
    for item in items:
        lines.append(f"- {item['quantity']} x {item['product_name']} = "
                     f"{naira(item['unit_price'] * item['quantity'])}")
    lines += ["", f"Total: {naira(order['total'])}",
              f"Payment: {order['payment_method']} (not yet paid)", "",
              f"Name: {order['customer_name']}", f"Phone: {order['phone']}",
              f"Delivery address: {order['address']}"]
    if order["notes"]:
        lines.append(f"Notes: {order['notes']}")
    return f"https://wa.me/{STORE['whatsapp']}?text={quote(chr(10).join(lines))}"


@app.route("/order/<order_number>")
def order_success(order_number):
    # Only the browser that placed the order can view it (privacy).
    if order_number not in session.get("my_orders", []):
        abort(404)
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,)).fetchone()
    if order is None:
        abort(404)
    items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)).fetchall()
    can_pay_online = (payments.paystack_enabled() and order["payment_method"] == PAYSTACK_LABEL
                      and order["payment_status"] != "Paid" and order["status"] != "Cancelled")
    return render_template("order_success.html", order=order, items=items,
                           wa_link=whatsapp_link(order, items), can_pay_online=can_pay_online)


# --------------------------------------------------------------------------
# Online payment routes (Paystack). Inactive unless PAYSTACK_SECRET_KEY is set.
# --------------------------------------------------------------------------


def mark_order_paid(order_number):
    """Only called after Paystack has confirmed the payment."""
    get_db().execute(
        "UPDATE orders SET payment_status = 'Paid' WHERE order_number = ? AND status != 'Cancelled'",
        (order_number,))


@app.post("/pay/<order_number>")
def pay_order(order_number):
    if order_number not in session.get("my_orders", []) or not payments.paystack_enabled():
        abort(404)
    order = get_db().execute("SELECT * FROM orders WHERE order_number = ?", (order_number,)).fetchone()
    if order is None or order["payment_status"] == "Paid" or order["status"] == "Cancelled":
        abort(404)
    if not order["email"]:
        flash("Online payment needs an email address on the order. Please pay on delivery or contact us.", "error")
        return redirect(url_for("order_success", order_number=order_number))
    url = start_online_payment(order_number, order["email"], order["total"])
    if url:
        return redirect(url)
    flash("The online payment page could not be opened. Please try again in a moment.", "error")
    return redirect(url_for("order_success", order_number=order_number))


@app.route("/payment/callback")
def payment_callback():
    """Customer returns here from Paystack. We verify with Paystack; we never trust the URL."""
    reference = (request.args.get("reference") or request.args.get("trxref") or "").strip()
    order = get_db().execute("SELECT * FROM orders WHERE order_number = ?", (reference,)).fetchone() if reference else None
    if order is None:
        abort(404)
    if order["payment_status"] != "Paid":
        if payments.paystack_enabled() and payments.paystack_verified(reference, order["total"]):
            mark_order_paid(reference)
            flash("Payment confirmed. Thank you!", "success")
        else:
            flash("We could not confirm your payment yet. If money left your account, "
                  "contact us with your order number.", "error")
    if reference in session.get("my_orders", []):
        return redirect(url_for("order_success", order_number=reference))
    return redirect(url_for("index"))


@app.post("/payment/webhook")
def payment_webhook():
    raw = request.get_data()
    if not payments.valid_webhook_signature(raw, request.headers.get("x-paystack-signature", "")):
        abort(400)
    event = request.get_json(silent=True) or {}
    data = event.get("data") or {}
    reference = data.get("reference") or ""
    if event.get("event") == "charge.success" and reference:
        order = get_db().execute("SELECT * FROM orders WHERE order_number = ?", (reference,)).fetchone()
        if order and order["payment_status"] != "Paid" and payments.paystack_verified(reference, order["total"]):
            mark_order_paid(reference)
    return "", 200


# --------------------------------------------------------------------------
# Admin area
# --------------------------------------------------------------------------
ADMIN_USERNAME = env("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = env("ADMIN_PASSWORD_HASH")
ORDER_STATUSES = ["Pending", "Confirmed", "Shipped", "Delivered", "Cancelled"]
PAYMENT_STATUSES = ["Unpaid", "Paid"]
MAX_IMAGE_BYTES = 5 * 1024 * 1024
LOGIN_FAILS = {}  # ip -> list of failure timestamps (resets when the site restarts)
MAX_FAILS, LOCK_SECONDS = 5, 600


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def recent_fails(ip):
    now = time.time()
    LOGIN_FAILS[ip] = [t for t in LOGIN_FAILS.get(ip, []) if now - t < LOCK_SECONDS]
    return len(LOGIN_FAILS[ip])


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    configured = bool(ADMIN_USERNAME and ADMIN_PASSWORD_HASH)
    error = None
    if request.method == "POST" and configured:
        ip = request.remote_addr or "unknown"
        if recent_fails(ip) >= MAX_FAILS:
            return render_template("admin_login.html", configured=configured,
                                   error="Too many failed attempts. Wait 10 minutes and try again."), 429
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user_ok = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
        pass_ok = check_password_hash(ADMIN_PASSWORD_HASH, password)  # always checked (same timing)
        if user_ok and pass_ok:
            target = request.form.get("next") or ""
            session.clear()  # new session on login
            session["is_admin"] = True
            session.permanent = True
            if not (target.startswith("/admin") and not target.startswith("//")):
                target = url_for("admin_dashboard")
            return redirect(target)
        LOGIN_FAILS.setdefault(ip, []).append(time.time())
        error = "Wrong username or password."
        return render_template("admin_login.html", configured=configured, error=error), 401
    return render_template("admin_login.html", configured=configured, error=error)


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "orders": db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "pending": db.execute("SELECT COUNT(*) FROM orders WHERE status = 'Pending'").fetchone()[0],
        "sales": db.execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status != 'Cancelled'").fetchone()[0],
        "paid": db.execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE payment_status = 'Paid' AND status != 'Cancelled'").fetchone()[0],
        "products": db.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "subscribers": db.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0],
    }
    recent = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 6").fetchall()
    low_stock = db.execute("SELECT * FROM products WHERE stock <= 5 ORDER BY stock ASC, name LIMIT 10").fetchall()
    return render_template("admin_dashboard.html", stats=stats, recent=recent, low_stock=low_stock)


@app.post("/admin/backup")
@admin_required
def admin_backup():
    """Download a safe copy of the whole database (orders, customers, products)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    target = sqlite3.connect(tmp.name)
    get_db().backup(target)  # consistent copy even while the site is running
    target.close()
    name = f"pajealex-backup-{datetime.now():%Y-%m-%d-%H%M}.db"
    response = send_file(tmp.name, as_attachment=True, download_name=name)
    response.call_on_close(lambda: os.path.exists(tmp.name) and os.remove(tmp.name))
    return response


# ---- Products ----


def detect_image_type(data):
    """Identify the real file type from its first bytes (not from its name)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_upload(file_storage):
    """Returns (filename, error). filename is None when no file was chosen."""
    if file_storage is None or not file_storage.filename:
        return None, None
    data = file_storage.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return None, "The photo is bigger than 5 MB. Please use a smaller one."
    kind = detect_image_type(data)
    if kind is None:
        return None, "The photo must be a real JPG, PNG, WEBP or GIF image."
    filename = f"{secrets.token_hex(12)}.{kind}"  # random name; the original name is never used
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as handle:
        handle.write(data)
    return filename, None


def delete_uploaded_image(name):
    """Delete only files we uploaded (never the sample images)."""
    name = os.path.basename(name or "")
    path = os.path.join(UPLOAD_DIR, name)
    if name and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def parse_product_form(form):
    values = {
        "name": " ".join((form.get("name") or "").split()),
        "description": (form.get("description") or "").strip(),
        "price": form.get("price", "").strip(),
        "stock": form.get("stock", "").strip(),
        "category": form.get("category") or "",
        "featured": 1 if form.get("featured") else 0,
        "best_seller": 1 if form.get("best_seller") else 0,
    }
    errors = {}
    if not 2 <= len(values["name"]) <= 120:
        errors["name"] = "Name must be 2 to 120 characters."
    if len(values["description"]) > 2000:
        errors["description"] = "Description can be at most 2000 characters."
    price = to_int(values["price"])
    if price is None or not 0 <= price <= 100_000_000:
        errors["price"] = "Enter the price in naira as a whole number, for example 15000."
    stock = to_int(values["stock"])
    if stock is None or not 0 <= stock <= 100_000:
        errors["stock"] = "Enter the stock as a whole number (0 or more)."
    if values["category"] not in CATEGORIES:
        errors["category"] = "Choose a category."
    values["price_int"], values["stock_int"] = price, stock
    return values, errors


@app.route("/admin/products")
@admin_required
def admin_products():
    products = get_db().execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return render_template("admin_products.html", products=products)


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_product_new():
    if request.method == "GET":
        return render_template("admin_product_form.html", product=None, values={}, errors={})
    values, errors = parse_product_form(request.form)
    filename, upload_error = save_upload(request.files.get("image"))
    if upload_error:
        errors["image"] = upload_error
    if errors:
        delete_uploaded_image(filename)
        return render_template("admin_product_form.html", product=None, values=values, errors=errors), 400
    get_db().execute(
        "INSERT INTO products (name, description, price, stock, category, image, featured, best_seller) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (values["name"], values["description"], values["price_int"], values["stock_int"],
         values["category"], filename or "placeholder.svg", values["featured"], values["best_seller"]))
    flash(f"{values['name']} was added.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)
    if request.method == "GET":
        return render_template("admin_product_form.html", product=product, values=dict(product), errors={})
    values, errors = parse_product_form(request.form)
    filename, upload_error = save_upload(request.files.get("image"))
    if upload_error:
        errors["image"] = upload_error
    if errors:
        delete_uploaded_image(filename)
        return render_template("admin_product_form.html", product=product, values=values, errors=errors), 400
    image = filename or product["image"]
    get_db().execute(
        "UPDATE products SET name=?, description=?, price=?, stock=?, category=?, image=?, "
        "featured=?, best_seller=? WHERE id=?",
        (values["name"], values["description"], values["price_int"], values["stock_int"],
         values["category"], image, values["featured"], values["best_seller"], product_id))
    if filename:
        delete_uploaded_image(product["image"])  # remove the replaced photo
    flash(f"{values['name']} was updated.", "success")
    return redirect(url_for("admin_products"))


@app.post("/admin/products/<int:product_id>/stock")
@admin_required
def admin_product_stock(product_id):
    product = get_product(product_id)
    stock = to_int(request.form.get("stock"))
    if product is None:
        abort(404)
    if stock is None or not 0 <= stock <= 100_000:
        flash("Stock must be a whole number, 0 or more.", "error")
    else:
        get_db().execute("UPDATE products SET stock = ? WHERE id = ?", (stock, product_id))
        flash(f"Stock for {product['name']} is now {stock}.", "success")
    return redirect(url_for("admin_products"))


@app.post("/admin/products/<int:product_id>/delete")
@admin_required
def admin_product_delete(product_id):
    product = get_product(product_id)
    if product is None:
        abort(404)
    get_db().execute("DELETE FROM products WHERE id = ?", (product_id,))
    delete_uploaded_image(product["image"])
    flash(f"{product['name']} was deleted. Past orders keep their records.", "info")
    return redirect(url_for("admin_products"))


# ---- Orders ----


@app.route("/admin/orders")
@admin_required
def admin_orders():
    status = request.args.get("status") or ""
    q = (request.args.get("q") or "").strip()[:60]
    sql, params = "SELECT * FROM orders WHERE 1=1", []
    if status in ORDER_STATUSES:
        sql += " AND status = ?"
        params.append(status)
    else:
        status = ""
    if q:
        sql += " AND (order_number LIKE ? OR customer_name LIKE ? OR phone LIKE ?)"
        params += [f"%{q}%"] * 3
    orders = get_db().execute(sql + " ORDER BY id DESC LIMIT 300", params).fetchall()
    return render_template("admin_orders.html", orders=orders, status=status, q=q, statuses=ORDER_STATUSES)


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_detail(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)
    items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    return render_template("admin_order_detail.html", order=order, items=items,
                           statuses=ORDER_STATUSES, payment_statuses=PAYMENT_STATUSES,
                           wa_customer=customer_whatsapp(order))


def customer_whatsapp(order):
    digits = re.sub(r"\D", "", order["phone"])
    if digits.startswith("0"):
        digits = "234" + digits[1:]  # Nigerian local number -> international
    return f"https://wa.me/{digits}" if len(digits) >= 11 else ""


@app.post("/admin/orders/<int:order_id>/update")
@admin_required
def admin_order_update(order_id):
    new_status = request.form.get("status")
    new_payment = request.form.get("payment_status")
    if new_status not in ORDER_STATUSES or new_payment not in PAYMENT_STATUSES:
        flash("Choose a valid status.", "error")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            db.execute("ROLLBACK")
            abort(404)
        items = db.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
        old_status = order["status"]
        if new_status == "Cancelled" and old_status != "Cancelled":
            for item in items:  # put the stock back
                db.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                           (item["quantity"], item["product_id"]))
        elif old_status == "Cancelled" and new_status != "Cancelled":
            for item in items:  # take the stock again, if it is still available
                exists = db.execute("SELECT 1 FROM products WHERE id = ?", (item["product_id"],)).fetchone()
                if exists:
                    done = db.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                                      (item["quantity"], item["product_id"], item["quantity"]))
                    if done.rowcount != 1:
                        raise ValueError(f"Not enough stock of {item['product_name']} to reopen this order.")
        db.execute("UPDATE orders SET status = ?, payment_status = ? WHERE id = ?",
                   (new_status, new_payment, order_id))
        db.execute("COMMIT")
    except ValueError as exc:
        db.execute("ROLLBACK")
        flash(str(exc), "error")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    flash("Order updated.", "success")
    return redirect(url_for("admin_order_detail", order_id=order_id))


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", code=400, title="Please try again",
                           message="Your form expired or was incomplete. Go back, refresh the page, and send it again."), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, title="Page not found",
                           message="We could not find that page. It may have moved or never existed."), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", code=413, title="File too large",
                           message="That upload is too big. Please use a smaller file."), 413


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error happened on our side. Please try again shortly."), 500


if __name__ == "__main__":
    app.run(debug=env("FLASK_DEBUG") == "1")
