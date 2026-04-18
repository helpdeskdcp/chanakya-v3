"""
Chanakya v3 — OTP System
Email + Telegram dual channel OTP
"""
import random, string, sqlite3, os
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = "data/users.db"

def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def save_otp(identifier, otp, purpose="verify"):
    """Save OTP to DB — expires in 10 minutes"""
    conn = sqlite3.connect(DB_PATH)
    # Delete old OTPs
    conn.execute("DELETE FROM otps WHERE identifier=? AND purpose=?",
                 (identifier, purpose))
    expiry = (datetime.now(IST) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS otps (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier  TEXT NOT NULL,
            otp         TEXT NOT NULL,
            purpose     TEXT DEFAULT 'verify',
            used        INTEGER DEFAULT 0,
            expiry      TEXT NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("INSERT INTO otps (identifier, otp, purpose, expiry) VALUES (?,?,?,?)",
                 (identifier, otp, purpose, expiry))
    conn.commit()
    conn.close()

def verify_otp(identifier, otp_input, purpose="verify"):
    """Verify OTP — returns True/False"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT, otp TEXT, purpose TEXT DEFAULT 'verify',
                used INTEGER DEFAULT 0, expiry TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        row = conn.execute("""
            SELECT * FROM otps
            WHERE identifier=? AND purpose=? AND used=0
            ORDER BY created_at DESC LIMIT 1
        """, (identifier, purpose)).fetchone()

        if not row:
            return False, "OTP not found or expired"

        # Check expiry
        expiry = datetime.strptime(row["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        if datetime.now(IST) > expiry:
            return False, "OTP expired — request new one"

        if row["otp"] != otp_input.strip():
            return False, "Invalid OTP"

        # Mark used
        conn.execute("UPDATE otps SET used=1 WHERE id=?", (row["id"],))
        conn.commit()
        return True, "OTP verified"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


# ── Email OTP ──────────────────────────────────────────
def send_email_otp(email, otp, purpose="verify"):
    """Send OTP via Email using SMTP"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host  = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port  = int(os.getenv("SMTP_PORT", "587"))
        smtp_user  = os.getenv("SMTP_USER", "")
        smtp_pass  = os.getenv("SMTP_PASS", "")

        if not smtp_user or not smtp_pass:
            return False, "Email not configured"

        purpose_map = {
            "verify":  "Account Verification",
            "reset":   "Password Reset",
            "login":   "Login Verification",
        }
        subject = f"Chanakya AI — {purpose_map.get(purpose, 'OTP')} Code"

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;
                    background:#0a0e1a;color:#e0e6f0;padding:32px;border-radius:12px">
          <div style="text-align:center;margin-bottom:24px">
            <div style="font-size:40px">⚡</div>
            <div style="color:#d4af37;font-size:24px;font-weight:800">CHANAKYA AI</div>
            <div style="color:#8090a8;font-size:12px">Quantum Neural Trading</div>
          </div>
          <div style="background:#111827;border:1px solid #1e3a5f;border-radius:10px;
                      padding:24px;text-align:center;margin-bottom:20px">
            <div style="color:#8090a8;font-size:13px;margin-bottom:8px">
              Your {purpose_map.get(purpose, 'OTP')} Code
            </div>
            <div style="color:#d4af37;font-size:48px;font-weight:800;
                        letter-spacing:12px;margin:8px 0">{otp}</div>
            <div style="color:#ff5252;font-size:11px">Valid for 10 minutes only</div>
          </div>
          <div style="background:rgba(255,82,82,.1);border:1px solid rgba(255,82,82,.3);
                      border-radius:8px;padding:12px;font-size:11px;color:#ff5252">
            ⚠️ Never share this OTP with anyone including Chanakya AI support.
          </div>
          <div style="margin-top:20px;padding:12px;background:#111827;border-radius:8px;
                      font-size:10px;color:#8090a8;text-align:center">
            Chanakya AI is an educational platform. Not SEBI registered.
            Trading involves market risk. Use at your own discretion.
          </div>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Chanakya AI <{smtp_user}>"
        msg["To"]      = email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.ehlo()
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, email, msg.as_string())

        return True, f"OTP sent to {email}"
    except Exception as e:
        return False, f"Email error: {e}"


# ── Telegram OTP ───────────────────────────────────────
def send_telegram_otp(telegram_id, otp, purpose="verify"):
    """Send OTP via Telegram bot"""
    try:
        import requests
        token = os.getenv("TELEGRAM_BOT_TOKEN","")
        if not token:
            return False, "Telegram not configured"

        purpose_map = {
            "verify": "Account Verification",
            "reset":  "Password Reset",
            "login":  "Login OTP",
        }

        msg = (
            f"⚡ <b>CHANAKYA AI</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔐 <b>{purpose_map.get(purpose,'OTP')}</b>\n\n"
            f"Your OTP: <code>{otp}</code>\n\n"
            f"⏰ Valid for <b>10 minutes</b>\n"
            f"⚠️ Never share this OTP with anyone."
        )
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": telegram_id, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
        if r.status_code == 200:
            return True, "OTP sent via Telegram"
        return False, f"Telegram error: {r.text}"
    except Exception as e:
        return False, f"Telegram error: {e}"


# ── Main Send OTP ──────────────────────────────────────
def send_otp(identifier, purpose="verify", channel=None):
    """
    Send OTP via best available channel.
    identifier = email or telegram_id
    """
    otp = generate_otp()
    save_otp(identifier, otp, purpose)

    # Detect channel
    if channel == "telegram" or (identifier.isdigit() and len(identifier) > 5):
        ok, msg = send_telegram_otp(identifier, otp, purpose)
        return ok, msg, "telegram"
    elif "@" in identifier:
        ok, msg = send_email_otp(identifier, otp, purpose)
        return ok, msg, "email"
    else:
        return False, "Invalid identifier (use email or Telegram ID)", None
