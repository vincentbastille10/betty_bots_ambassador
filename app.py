import os
import sqlite3
import secrets
import datetime
from contextlib import closing

from flask import Flask, render_template, request, redirect, url_for, abort, Response, jsonify

BANNED_EMAILS = {
    "hisseinadamabba28@gmail.com"
}

BANNED_CODES = {
    "R1GNAG"
}

# --------------------
# dotenv (OPTIONNEL)
# --------------------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# --------------------
# Mailing (OPTIONNEL)
# --------------------
try:
    from mailing import send_ambassador_welcome_email  # type: ignore
except Exception:
    send_ambassador_welcome_email = None


# --------------------
# Config
# --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Render Disk: DB_PATH doit venir de l'env si présent
# Ex: DB_PATH=/var/data/ambassadors.db
DB_PATH = (os.environ.get("DB_PATH") or "").strip()
if not DB_PATH:
    DB_PATH = os.path.join(BASE_DIR, "database", "ambassadors.db")

DB_DIR = os.path.dirname(DB_PATH)

APP_BASE_URL = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
if not APP_BASE_URL:
    APP_BASE_URL = None  # fallback url_for(_external=True)

ADMIN_TOKEN = (os.environ.get("ADMIN_TOKEN") or "").strip()

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
                updated_at TEXT,

                clicks INTEGER NOT NULL DEFAULT 0,
                signups INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def db_migrate():
    """Ajoute des colonnes si la DB existait déjà (sans casser)."""
    with closing(get_db()) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(ambassadors)").fetchall()}

        def add(name: str, sql: str):
            if name not in cols:
                conn.execute(sql)

        add("updated_at", "ALTER TABLE ambassadors ADD COLUMN updated_at TEXT")
        conn.commit()


init_db()
db_migrate()


def now_utc_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def generate_code(conn: sqlite3.Connection) -> str:
    """Code lisible 6 chars unique."""
    for _ in range(50):
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


def require_admin():
    token = (request.args.get("token") or "").strip()
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        abort(403)


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

        # Obligatoires
        if not name or not email:
            error = "Merci de remplir au minimum votre nom et votre email."
        elif "@" not in email or "." not in email:
            error = "Email invalide."
        elif not accept_terms:
            error = "Merci de cocher la case d’acceptation des conditions pour continuer."
        else:
            payout_preference_db = payout_preference or None
            payout_identifier_db = payout_identifier or None

            created_now = now_utc_iso()
            updated_now = created_now
            is_new = False

            with closing(get_db()) as conn:
                existing = conn.execute(
                    "SELECT * FROM ambassadors WHERE email = ?",
                    (email,),
                ).fetchone()

                if existing:
                    code = existing["code"]

                    # update souple : on n’écrase JAMAIS avec du vide
                    updates = []
                    params = []

                    if name and name != (existing["name"] or ""):
                        updates.append("name = ?")
                        params.append(name)

                    if payout_preference_db is not None and payout_preference_db != (existing["payout_preference"] or None):
                        updates.append("payout_preference = ?")
                        params.append(payout_preference_db)

                    if payout_identifier_db is not None and payout_identifier_db != (existing["payout_identifier"] or None):
                        updates.append("payout_identifier = ?")
                        params.append(payout_identifier_db)

                    # toujours updated_at
                    updates.append("updated_at = ?")
                    params.append(updated_now)

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
                            created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (name, email, code, payout_preference_db, payout_identifier_db, created_now, updated_now),
                    )
                    conn.commit()
                    is_new = True

            # email de bienvenue (non bloquant)
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

            # ✅ IMPORTANT : redirection immédiate dashboard
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

        clicks = int(ambassador["clicks"] or 0)
        signups = int(ambassador["signups"] or 0)

        price = 79.90
        upfront_per = 0.30 * price
        recurring_per_month = 10.0

        est_upfront_total = signups * upfront_per
        est_monthly_recurring = signups * recurring_per_month
        est_6m_total = signups * (upfront_per + recurring_per_month * 6)

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
        if ambassador:
            conn.execute(
                "UPDATE ambassadors SET clicks = clicks + 1, updated_at = ? WHERE id = ?",
                (now_utc_iso(), ambassador["id"]),
            )
            conn.commit()

    return redirect(build_tracking_target(code))


# --------------------
# ADMIN
# --------------------
@app.route("/admin/ambassadors")
def admin_ambassadors():
    require_admin()

    with closing(get_db()) as conn:
        rows = conn.execute(
            """
            SELECT id, name, email, code,
                   payout_preference, payout_identifier,
                   created_at, updated_at,
                   clicks, signups
            FROM ambassadors
            ORDER BY datetime(created_at) DESC
            """
        ).fetchall()

    return render_template("admin_ambassadors.html", ambassadors=rows)


@app.route("/admin/ambassadors.json")
def admin_ambassadors_json():
    require_admin()

    with closing(get_db()) as conn:
        rows = conn.execute(
            """
            SELECT id, name, email, code,
                   payout_preference, payout_identifier,
                   created_at, updated_at,
                   clicks, signups
            FROM ambassadors
            ORDER BY datetime(created_at) DESC
            """
        ).fetchall()

    data = []
    for r in rows:
        data.append({k: r[k] for k in r.keys()})
    return jsonify({"db": DB_PATH, "count": len(data), "ambassadors": data})


@app.route("/admin/ambassadors.csv")
def admin_ambassadors_csv():
    require_admin()

    with closing(get_db()) as conn:
        rows = conn.execute(
            """
            SELECT id, name, email, code,
                   payout_preference, payout_identifier,
                   created_at, updated_at,
                   clicks, signups
            FROM ambassadors
            ORDER BY datetime(created_at) DESC
            """
        ).fetchall()

    header = "id,name,email,code,payout_preference,payout_identifier,created_at,updated_at,clicks,signups\n"
    lines = [header]

    def esc(v):
        v = "" if v is None else str(v)
        v = v.replace('"', '""')
        return f'"{v}"'

    for r in rows:
        lines.append(",".join([
            esc(r["id"]), esc(r["name"]), esc(r["email"]), esc(r["code"]),
            esc(r["payout_preference"]), esc(r["payout_identifier"]),
            esc(r["created_at"]), esc(r["updated_at"]),
            esc(r["clicks"]), esc(r["signups"]),
        ]) + "\n")

    return Response("".join(lines), mimetype="text/csv")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
