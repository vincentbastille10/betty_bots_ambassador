import os
import sqlite3
import secrets
import datetime
from contextlib import closing

from flask import Flask, render_template, request, redirect, url_for

# --------------------
# dotenv (OPTIONNEL)
# --------------------
# Sur Render, tu n'en as pas besoin. En local, si python-dotenv est installé, ça charge .env
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# --------------------
# Mailing (OPTIONNEL)
# --------------------
# mailing.py doit exposer:
# send_ambassador_welcome_email(to_email, firstname, code, dashboard_url, short_link, tracking_target, is_new)
try:
    from mailing import send_ambassador_welcome_email  # type: ignore
except Exception:
    send_ambassador_welcome_email = None


# --------------------
# Config
# --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "betty.db")

APP_BASE_URL = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
if not APP_BASE_URL:
    APP_BASE_URL = None  # fallback url_for(_external=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# --------------------
# DB helpers
# --------------------
def ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def get_db():
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    ensure_db_dir()
    with closing(get_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ambassadors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE,
                payout_preference TEXT,
                payout_identifier TEXT,
                created_at TEXT NOT NULL,
                clicks INTEGER NOT NULL DEFAULT 0,
                signups INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


init_db()


def generate_code(conn: sqlite3.Connection) -> str:
    """Génère un code ambassadeur lisible (6 chars) unique."""
    for _ in range(30):
        candidate = secrets.token_urlsafe(4)[:6]
        candidate = candidate.replace("-", "A").replace("_", "B").upper()
        row = conn.execute("SELECT 1 FROM ambassadors WHERE code = ?", (candidate,)).fetchone()
        if not row:
            return candidate
    raise RuntimeError("Impossible de générer un code ambassadeur unique.")


def build_dashboard_url(code: str) -> str:
    if APP_BASE_URL:
        return f"{APP_BASE_URL}/dashboard?code={code}"
    return url_for("dashboard", code=code, _external=True)


def build_short_link(code: str) -> str:
    if APP_BASE_URL:
        return f"{APP_BASE_URL}/l/{code}"
    return url_for("redirect_with_ref", code=code, _external=True)


def build_tracking_target(code: str) -> str:
    return f"https://www.spectramedia.online/?ref={code}"


# --------------------
# Routes
# --------------------
@app.route("/")
def index():
    return redirect(url_for("inscription"))


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    error = None

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()

        payout_preference = (request.form.get("payout_preference") or "").strip()
        payout_identifier = (request.form.get("payout_identifier") or "").strip()

        accept_terms = (request.form.get("accept_terms") or "").strip()

        # ✅ Obligatoires : name + email + accept_terms
        if not name or not email:
            error = "Merci de remplir au minimum votre nom et votre email."
        elif not accept_terms:
            error = "Merci de cocher la case d’acceptation des conditions pour continuer."
        else:
            payout_preference_db = payout_preference or None
            payout_identifier_db = payout_identifier or None

            created_now = datetime.datetime.utcnow().isoformat()
            is_new = False

            with closing(get_db()) as conn:
                existing = conn.execute(
                    "SELECT * FROM ambassadors WHERE email = ?",
                    (email,),
                ).fetchone()

                if existing:
                    code = existing["code"]

                    # update souple : on n’écrase pas avec du vide
                    updates = []
                    params = []

                    if name and name != (existing["name"] or ""):
                        updates.append("name = ?")
                        params.append(name)

                    if payout_preference_db is not None:
                        updates.append("payout_preference = ?")
                        params.append(payout_preference_db)

                    if payout_identifier_db is not None:
                        updates.append("payout_identifier = ?")
                        params.append(payout_identifier_db)

                    if updates:
                        params.append(email)
                        conn.execute(
                            f"UPDATE ambassadors SET {', '.join(updates)} WHERE email = ?",
                            tuple(params),
                        )
                        conn.commit()
                else:
                    code = generate_code(conn)
                    conn.execute(
                        """
                        INSERT INTO ambassadors (
                            name, email, code,
                            payout_preference, payout_identifier,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (name, email, code, payout_preference_db, payout_identifier_db, created_now),
                    )
                    conn.commit()
                    is_new = True

            # ✅ Envoi mail AVANT redirect
            if send_ambassador_welcome_email:
                try:
                    firstname = (name.split(" ")[0] if name else "")
                    dashboard_url = build_dashboard_url(code)
                    short_link = build_short_link(code)
                    tracking_target = build_tracking_target(code)

                    send_ambassador_welcome_email(
                        to_email=email,
                        firstname=firstname,
                        code=code,
                        dashboard_url=dashboard_url,
                        short_link=short_link,
                        tracking_target=tracking_target,
                        is_new=is_new,
                    )
                except Exception:
                    app.logger.exception("Erreur envoi email Mailjet (inscription ambassadeur)")

            return redirect(url_for("dashboard", code=code))

    return render_template("inscription.html", error=error)


@app.route("/dashboard")
def dashboard():
    code = (request.args.get("code") or request.args.get("ref") or "").strip().upper()
    email = (request.args.get("email") or "").strip().lower()

    with closing(get_db()) as conn:
        ambassador = None

        if code:
            ambassador = conn.execute("SELECT * FROM ambassadors WHERE code = ?", (code,)).fetchone()
        elif email:
            ambassador = conn.execute("SELECT * FROM ambassadors WHERE email = ?", (email,)).fetchone()

        if not ambassador:
            return render_template("dashboard.html", ambassador=None, stats=None, not_found=True)

        clicks = int(ambassador["clicks"])
        signups = int(ambassador["signups"])

        price = 79.90
        upfront_per = 0.30 * price
        recurring_per_month = 10.0

        est_upfront_total = signups * upfront_per
        est_monthly_recurring = signups * recurring_per_month
        est_6m_total = signups * (upfront_per + recurring_per_month * 6)

        # Pour être cohérent avec APP_BASE_URL
        short_link = build_short_link(ambassador["code"])
        tracking_link = short_link

        stats = {
            "clicks": clicks,
            "signups": signups,
            "tracking_link": tracking_link,
            "short_link": short_link,
            "upfront_per": upfront_per,
            "est_upfront_total": est_upfront_total,
            "est_monthly_recurring": est_monthly_recurring,
            "est_6m_total": est_6m_total,
        }

        return render_template(
            "dashboard.html",
            ambassador=ambassador,
            betty_link=tracking_link,
            total_sales=signups,
            total_clicks=clicks,
            total_commission=est_6m_total,
            stats=stats,
            not_found=False,
        )


@app.route("/l/<code>")
def redirect_with_ref(code):
    code = (code or "").strip().upper()

    with closing(get_db()) as conn:
        ambassador = conn.execute("SELECT * FROM ambassadors WHERE code = ?", (code,)).fetchone()

        ref_code = code
        if ambassador:
            conn.execute("UPDATE ambassadors SET clicks = clicks + 1 WHERE id = ?", (ambassador["id"],))
            conn.commit()
            ref_code = ambassador["code"]

    return redirect(build_tracking_target(ref_code))

from flask import abort, Response

@app.route("/admin/ambassadors")
def admin_ambassadors():
    # Protection simple par token (mets ADMIN_TOKEN dans Render > Environment)
    token = (request.args.get("token") or "").strip()
    admin_token = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if not admin_token or token != admin_token:
        abort(403)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, name, email, code, payout_preference, payout_identifier,
               created_at, clicks, signups
        FROM ambassadors
        ORDER BY datetime(created_at) DESC
        """
    ).fetchall()
    conn.close()

    return render_template("admin_ambassadors.html", ambassadors=rows)


@app.route("/admin/ambassadors.csv")
def admin_ambassadors_csv():
    token = (request.args.get("token") or "").strip()
    admin_token = (os.environ.get("ADMIN_TOKEN") or "").strip()
    if not admin_token or token != admin_token:
        abort(403)

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, name, email, code, payout_preference, payout_identifier,
               created_at, clicks, signups
        FROM ambassadors
        ORDER BY datetime(created_at) DESC
        """
    ).fetchall()
    conn.close()

    # CSV simple
    header = "id,name,email,code,payout_preference,payout_identifier,created_at,clicks,signups\n"
    lines = [header]
    for r in rows:
        def esc(v):
            v = "" if v is None else str(v)
            v = v.replace('"', '""')
            return f'"{v}"'
        lines.append(",".join([
            esc(r["id"]), esc(r["name"]), esc(r["email"]), esc(r["code"]),
            esc(r["payout_preference"]), esc(r["payout_identifier"]),
            esc(r["created_at"]), esc(r["clicks"]), esc(r["signups"])
        ]) + "\n")

    return Response("".join(lines), mimetype="text/csv")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
