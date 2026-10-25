"""Creates the secure password hash for your admin login.

Run:  python make_admin_hash.py
Then copy the two printed lines into your .env file (or into Render's
Environment settings). Your real password is never stored anywhere.
"""
import getpass

from werkzeug.security import generate_password_hash

username = input("Choose an admin username: ").strip()
password = getpass.getpass("Choose a password (at least 10 characters, hidden as you type): ")
again = getpass.getpass("Type the password again: ")

if len(username) < 3:
    raise SystemExit("Username must be at least 3 characters.")
if password != again:
    raise SystemExit("The passwords did not match. Run the script again.")
if len(password) < 10:
    raise SystemExit("Password must be at least 10 characters.")

print("\nAdd these two lines to your .env file (keep the single quotes):\n")
print(f"ADMIN_USERNAME={username}")
print(f"ADMIN_PASSWORD_HASH='{generate_password_hash(password)}'")
