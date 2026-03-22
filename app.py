import os
import secrets
import datetime
from contextlib import closing

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, abort, Response, jsonify

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

APP_BASE_URL = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
if not APP_BASE_URL:
    APP_BASE_URL = None  # fallback url_for(_external=True)

ADMIN_TOKEN = (os.environ.get("ADMIN_TOKEN") or "").strip()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# --------------------
# ✅ Bannissement dur par env vars (email + code)
# --------------------
BANNED_EMAILS_RAW = os.environ.get("BANNED_EMAILS", "")
BANNED_CODES_RAW = os.environ.get("BANNED_CODES", "")


def _parse_csv_set(raw: str, mode: str = "lower"):
    items = []
    for part in raw.replace("\n", ",").split(","):
        v = (part or "").strip()
        if not v:
            continue
        if mode == "lower":
            items.append(v.lower())
        elif mode == "upper":
            items.append(v.upper())
        else:
            items.append(v)
    return set(items)


BANNED_EMAILS = _parse_csv_set(BANNED_EMAILS_RAW, mode="lower")
BANNED_CODES = _parse_csv_set(BANNED_CODES_RAW, mode="upper")


def is_banned_email(email: str) -> bool:
    e = (email or "").strip().lower()
    return bool(e) and e in BANNED_EMAILS


def is_banned_code(code: str) -> bool:
    c = (code or "").strip().upper()
    return bool(c) and c in BANNED_CODES


def hard_block(message: str = "Accès indisponible."):
    return render_template("error.html", message=message), 403


# --------------------
# DB helpers
# --------------------
def get_db():
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL manquante")

    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def init_db():
    with closing(get_db()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ambassadors (
                    id SERIAL PRIMARY KEY,

                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    code TEXT UNIQUE NOT NULL,

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
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'ambassadors'
                """
            )
            cols = {r["column_name"] for r in cur.fetchall()}

            if "updated_at" not in cols:
                cur.execute("ALTER TABLE ambassadors ADD COLUMN updated_at TEXT")

            conn.commit()


init_db()
db_migrate()


def now_utc_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def generate_code(conn) -> str:
    """Code lisible 6 chars unique."""
    for _ in range(50):
        candidate = secrets.token_urlsafe(4)[:6]
        candidate = candidate.replace("-", "A").replace("_", "B").upper()

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM ambassadors WHERE code = %s", (candidate,))
            row = cur.fetchone()

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
        email = (request.form.get("email") or "").lower().strip()

        if is_banned_email(email):
            return hard_block("Inscription indisponible.")

        payout_preference = (request.form.get("payout_preference") or "").strip()
        payout_identifier = (request.form.get("payout_identifier") or "").strip()
        accept_terms = (request.form.get("accept_terms") or "").strip()

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
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM ambassadors WHERE email = %s",
                        (email,),
                    )
                    existing = cur.fetchone()

                    if existing:
                        code = existing["code"]

                        if is_banned_code(code) or is_banned_email(existing["email"]):
                            return hard_block("Accès indisponible.")

                        updates = []
                        params = []

                        if name and name != (existing["name"] or ""):
                            updates.append("name = %s")
                            params.append(name)

                        if (
                            payout_preference_db is not None
                            and payout_preference_db != existing["payout_preference"]
                        ):
                            updates.append("payout_preference = %s")
                            params.append(payout_preference_db)

                        if (
                            payout_identifier_db is not None
                            and payout_identifier_db != existing["payout_identifier"]
                        ):
                            updates.append("payout_identifier = %s")
                            params.append(payout_identifier_db)

                        updates.append("updated_at = %s")
                        params.append(updated_now)

                        params.append(email)

                        cur.execute(
                            f"UPDATE ambassadors SET {', '.join(updates)} WHERE email = %s",
                            tuple(params),
                        )
                        conn.commit()
                    else:
                        code = generate_code(conn)

                        if is_banned_code(code):
                            return hard_block("Inscription indisponible.")

                        cur.execute(
                            """
                            INSERT INTO ambassadors (
                                name, email, code,
                                payout_preference, payout_identifier,
                                created_at, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                name,
                                email,
                                code,
                                payout_preference_db,
                                payout_identifier_db,
                                created_now,
                                updated_now,
                            ),
                        )
                        conn.commit()
                        is_new = True

            if send_ambassador_welcome_email:
                try:
                    firstname = name.split(" ")[0] if name else ""
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

    if code and is_banned_code(code):
        return hard_block("Accès indisponible.")
    if email and is_banned_email(email):
        return hard_block("Accès indisponible.")

    with closing(get_db()) as conn:
        with conn.cursor() as cur:
            ambassador = None

            if code:
                cur.execute("SELECT * FROM ambassadors WHERE code = %s", (code,))
                ambassador = cur.fetchone()
            elif email:
                cur.execute("SELECT * FROM ambassadors WHERE email = %s", (email,))
                ambassador = cur.fetchone()

        if not ambassador:
            return render_template("dashboard.html", ambassador=None, stats=None, not_found=True)

        if is_banned_email(ambassador["email"]) or is_banned_code(ambassador["code"]):
            return hard_block("Accès indisponible.")

        clicks = int(ambassador["clicks"] or 0)
        signups = int(ambassador["signups"] or 0)

        price = 129.0
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

    if is_banned_code(code):
        abort(404)

    with closing(get_db()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ambassadors WHERE code = %s", (code,))
            ambassador = cur.fetchone()

            if ambassador:
                if is_banned_email(ambassador["email"]) or is_banned_code(ambassador["code"]):
                    abort(404)

                cur.execute(
                    "UPDATE ambassadors SET clicks = clicks + 1, updated_at = %s WHERE id = %s",
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
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, code,
                       payout_preference, payout_identifier,
                       created_at, updated_at,
                       clicks, signups
                FROM ambassadors
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    return render_template("admin_ambassadors.html", ambassadors=rows)


@app.route("/admin/ambassadors.json")
def admin_ambassadors_json():
    require_admin()

    with closing(get_db()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, code,
                       payout_preference, payout_identifier,
                       created_at, updated_at,
                       clicks, signups
                FROM ambassadors
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    data = []
    for r in rows:
        data.append(dict(r))

    return jsonify({"db": "postgres", "count": len(data), "ambassadors": data})


@app.route("/admin/ambassadors.csv")
def admin_ambassadors_csv():
    require_admin()

    with closing(get_db()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, code,
                       payout_preference, payout_identifier,
                       created_at, updated_at,
                       clicks, signups
                FROM ambassadors
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    header = "id,name,email,code,payout_preference,payout_identifier,created_at,updated_at,clicks,signups\n"
    lines = [header]

    def esc(v):
        v = "" if v is None else str(v)
        v = v.replace('"', '""')
        return f'"{v}"'

    for r in rows:
        lines.append(
            ",".join(
                [
                    esc(r["id"]),
                    esc(r["name"]),
                    esc(r["email"]),
                    esc(r["code"]),
                    esc(r["payout_preference"]),
                    esc(r["payout_identifier"]),
                    esc(r["created_at"]),
                    esc(r["updated_at"]),
                    esc(r["clicks"]),
                    esc(r["signups"]),
                ]
            )
            + "\n"
        )

    return Response("".join(lines), mimetype="text/csv")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
