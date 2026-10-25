# Pajealex Fashion Hub

A complete online fashion store built with Flask, SQLite, HTML, CSS and JavaScript.
Naira prices, cart, checkout, WhatsApp ordering, cash on delivery, admin dashboard,
product photo uploads, order management and Paystack-ready online payments.

---

## 1. Run it on your computer (Windows Command Prompt)

Install Python 3.11 or newer from python.org. Tick **"Add python.exe to PATH"** during install.

```
cd C:\path\to\pajealex_fashion_hub
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
python make_admin_hash.py
```

1. Open `.env` in Notepad.
2. Paste the long random text after `SECRET_KEY=`.
3. Paste the two lines printed by `make_admin_hash.py` (`ADMIN_USERNAME` and `ADMIN_PASSWORD_HASH`). Keep the single quotes around the hash.
4. Set `WHATSAPP_NUMBER` to your real business number: country code first, digits only (format `234XXXXXXXXXX`).
5. Fill in `STORE_PHONE`, `STORE_EMAIL`, `STORE_ADDRESS` and your social links if you want them in the footer.

Start the site:

```
python app.py
```

- Store: http://127.0.0.1:5000
- Admin: http://127.0.0.1:5000/admin/login

Stop it with `Ctrl + C`. The database `instance\store.db` is created automatically with the 3 sample products.
After editing `.env`, stop the site and start it again.

---

## 2. Using the admin dashboard

- **Dashboard:** total orders, pending orders, total sales (cancelled orders excluded), confirmed paid amount, low-stock list, and a **Download backup** button.
- **Products:** add, edit, delete, upload a photo, quick-edit stock. Tick "Featured" or "Best seller" to show a product in those homepage sections.
- **Orders:** search by order number, name or phone; filter by status; open an order to see the customer's phone, email and delivery address, message them on WhatsApp, and change the status (Pending, Confirmed, Shipped, Delivered, Cancelled).
- **Payment status:** only set an order to **Paid** after you have really received the money. Cancelling an order puts its items back into stock.

Photos: JPG, PNG, WEBP or GIF up to 5 MB. Square pictures (for example 1000 x 1000) look best.
The three sample pictures are placeholders. Replace them by editing each product in the admin.

---

## 3. Folder guide

| File or folder | Purpose |
|---|---|
| `app.py` | All backend code: database, store, cart, checkout, admin, security |
| `payments.py` | Paystack payment helpers (inactive until you add a key) |
| `make_admin_hash.py` | Creates your secure admin password hash |
| `requirements.txt` | Python packages (Flask, python-dotenv, gunicorn) |
| `.env.example` | Template for your private settings. Copy to `.env` |
| `.python-version` | Tells Render which Python to use |
| `templates/` | HTML pages (`admin_*.html` are the admin pages) |
| `static/css/style.css`, `static/js/main.js` | Styling and interactivity |
| `static/images/` | Sample placeholder pictures |
| `instance/` | Database and uploaded photos (never uploaded to GitHub) |

---

## 4. Online payments with Paystack (test mode first)

Without a Paystack key the store offers WhatsApp order and cash on delivery only, and every order is saved as **Unpaid**.

To try online payment safely:

1. Create a Paystack account and open **Settings > API Keys & Webhooks**.
2. Copy the **Test Secret Key** (starts with `sk_test_`) into `.env` as `PAYSTACK_SECRET_KEY=`. Restart the site.
3. Checkout now shows "Pay online (Paystack)". It requires the customer's email.
4. Place a test order and pay with the test card details shown in Paystack's documentation.
5. After you return to the site, the order becomes **Paid** only if Paystack confirms the payment and the amount matches the order total.
6. When deployed, set the **Webhook URL** in the Paystack dashboard to `https://YOUR-SITE.onrender.com/payment/webhook`. The site only accepts webhooks with a valid Paystack signature.
7. Go live only after testing: replace the test key with your live key (`sk_live_...`) in Render's environment settings. Never put keys in code or on GitHub.

Flutterwave can be added in the same way: write initialize and verify functions in `payments.py` and call them from the payment routes in `app.py`.

---

## 5. Upload to GitHub (Windows)

1. Install Git from git-scm.com and create a free account at github.com.
2. On GitHub, click **New repository**, name it `pajealex-fashion-hub`, keep it **Private**, do not add a README, and click **Create repository**.
3. In Command Prompt, inside the project folder:

```
git init
git add .
git commit -m "Pajealex Fashion Hub"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/pajealex-fashion-hub.git
git push -u origin main
```

4. Check that secrets did not upload. This command must NOT list `.env` or anything in `instance`:

```
git ls-files
```

If `.env` appears, stop, run `git rm --cached .env`, commit, and change every key in it, because it was exposed.

To update the live site later: `git add .`, `git commit -m "describe the change"`, `git push`. Render redeploys automatically.

---

## 6. Deploy on Render

1. Sign in at render.com with your GitHub account.
2. Click **New > Web Service** and choose your `pajealex-fashion-hub` repository.
3. Settings:
   - **Language:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT`
4. Under **Environment** add these variables:

| Name | Value |
|---|---|
| `SECRET_KEY` | long random text (generate with the command in section 1) |
| `ADMIN_USERNAME` | your admin username |
| `ADMIN_PASSWORD_HASH` | the hash from `make_admin_hash.py` (paste without the surrounding quotes) |
| `WHATSAPP_NUMBER` | `234XXXXXXXXXX` format |
| `STORE_PHONE`, `STORE_EMAIL`, `STORE_ADDRESS` | your contact details |
| `INSTAGRAM_URL`, `FACEBOOK_URL`, `TIKTOK_URL` | optional |
| `COOKIE_SECURE` | `1` |
| `BEHIND_PROXY` | `1` |
| `DATABASE_PATH` | `/var/data/store.db` (see persistent disk below) |
| `UPLOAD_DIR` | `/var/data/uploads` |
| `PAYSTACK_SECRET_KEY` | optional, test key first |

5. Click **Create Web Service** and wait for the deploy. Render gives you a `https://....onrender.com` address.

Use one worker (`--workers 1`). SQLite is a single-file database and works best this way; the threads handle several visitors at once.

### Persistent disk and backups (important)

A Render web service has a temporary file system. **Without a persistent disk, your database and uploaded photos are erased on every deploy and restart.** That means lost orders.

- Attach a **Disk** to the web service (in the service's **Disks** section) with mount path `/var/data`, and set `DATABASE_PATH` and `UPLOAD_DIR` as in the table above.
- As far as I know, disks are only available on Render's paid instance types, and the free tier also sleeps when idle. Check Render's pricing page before you launch a real store.
- If you cannot use a disk yet, treat the site as a demo and not for real orders.
- **Back up regularly:** log in to the admin and click **Download backup** on the dashboard (do this weekly, and before big changes). Keep the file somewhere safe and private because it contains customer details. Uploaded photos live in `UPLOAD_DIR`; keep your original product photos on your computer or phone as their backup.
- Render can also take disk snapshots; check its dashboard for current options.
- When your store grows, a hosted database such as PostgreSQL is the next step.

---

## 7. Test the website before launch (checklist)

**Store**
- [ ] Home, Shop, Categories menu, About and Contact open without errors
- [ ] Search and filters work; "No products found" message appears for nonsense search
- [ ] Add to cart, increase, decrease, remove; totals are correct; cart survives a refresh
- [ ] Adding more than the stock is refused with a clear message
- [ ] Empty cart shows a helpful message
- [ ] Checkout rejects a bad phone number but keeps what you typed
- [ ] A valid order shows an order number and confirmation page
- [ ] The WhatsApp button opens WhatsApp **to your number** with the order details
- [ ] Footer shows your real phone, email and social links
- [ ] Phone check: menu button works, pages fit the screen

**Admin**
- [ ] `/admin` redirects to the login page when you are logged out
- [ ] Wrong password is refused; correct password works; Log out works
- [ ] Add a product with a photo; it appears in the shop; edit it; delete it
- [ ] The new order appears in Orders with the customer's details
- [ ] Change status to Shipped and back; cancel an order and check the stock returns
- [ ] Download backup works

**Before real customers**
- [ ] Real photos, names, prices and descriptions replace all the samples
- [ ] Sample reviews on the homepage are replaced or removed
- [ ] `SECRET_KEY` is set; `COOKIE_SECURE=1`; the persistent disk is attached
- [ ] If using Paystack: test payment succeeds in test mode, webhook URL is set, then switch to the live key
- [ ] `git ls-files` shows no `.env`

---

## 8. Common errors

| Problem | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python and tick "Add python.exe to PATH" |
| `No module named flask` | Run `venv\Scripts\activate`, then `pip install -r requirements.txt` |
| `Address already in use` | Another copy is running. Close it with `Ctrl + C` |
| Admin page says "not set up yet" | Run `make_admin_hash.py`, paste both lines into `.env`, restart |
| Right password but login fails after pasting hash | Keep the single quotes around the hash in `.env`; paste without quotes on Render |
| "Too many failed attempts" | Wait 10 minutes (or restart the site) |
| Cart or admin login resets on restart | `SECRET_KEY` is empty |
| Page says "Please try again" (400) | The form expired. Refresh and submit again |
| Photos disappear on Render | No persistent disk, or `UPLOAD_DIR` does not point to it |
| Orders disappear on Render | No persistent disk, or `DATABASE_PATH` does not point to it |
| Paystack button missing | `PAYSTACK_SECRET_KEY` is empty or the site was not restarted |
| Order stays Unpaid after paying | Paystack could not confirm it; check the key matches the mode (test or live) and the webhook URL |
| Edited `.env` but nothing changed | Stop the site and run `python app.py` again |

---

## 9. Security built in

- Admin pages need login. Passwords are stored only as a salted hash; secrets live in environment variables.
- Five wrong logins lock that address out for 10 minutes. Logging in starts a fresh session.
- Every form (including admin actions and logout) has a CSRF token.
- All database queries use parameters, so SQL injection does not work.
- Photo uploads are checked by their real file contents (not their name), limited to 5 MB, and stored under random names.
- Prices and totals are always calculated on the server. Stock is re-checked inside a database transaction when an order is placed.
- An order is marked Paid only after Paystack's own servers confirm the payment and the amount.
- Order confirmation pages open only in the browser that placed the order. Customer details are visible only to a logged-in admin.
- Cookies are HttpOnly and SameSite. Admin pages are never cached.

What still depends on you: choosing a strong admin password, keeping `.env` private, attaching a persistent disk, and taking regular backups.
