import os
import sqlite3
import secrets
import datetime
from contextlib import closing

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for

# Optionnel: mailing.py à la racine
# from mailing import send_ambassador_welcome_email


# --------------------
# Config
# --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "betty.db")

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
    """
    Génère un code ambassadeur lisible (6 chars) unique.
    """
    for _ in range(20):
        candidate = secrets.token_urlsafe(4)[:6]
        candidate = candidate.replace("-", "A").replace("_", "B").upper()

        row = conn.execute(
            "SELECT 1 FROM ambassadors WHERE code = ?",
            (candidate,),
        ).fetchone()

        if not row:
            return candidate

    raise RuntimeError("Impossible de générer un code ambassadeur unique.")


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

        if not name or not email or not payout_preference or not payout_identifier:
            error = "Merci de remplir tous les champs obligatoires pour rejoindre le programme ambassadeur."
        elif not accept_terms:
            error = "Merci de cocher la case d’acceptation des conditions pour continuer."
        else:
            with closing(get_db()) as conn:
                existing = conn.execute(
                    "SELECT * FROM ambassadors WHERE email = ?",
                    (email,),
                ).fetchone()

                now = datetime.datetime.utcnow().isoformat()

                if existing:
                    code = existing["code"]

                    # Optionnel: si tu veux mettre à jour ses infos de paiement au passage
                    conn.execute(
                        """
                        UPDATE ambassadors
                        SET name = ?, payout_preference = ?, payout_identifier = ?
                        WHERE email = ?
                        """,
                        (name, payout_preference, payout_identifier, email),
                    )
                    conn.commit()

                    # Optionnel: renvoyer le mail même si déjà existant
                    # send_welcome = True
                else:
                    code = generate_code(conn)
                    conn.execute(
                        """
                        INSERT INTO ambassadors (
                            name, email, code, payout_preference,
                            payout_identifier, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (name, email, code, payout_preference, payout_identifier, now),
                    )
                    conn.commit()

                    # send_welcome = True

            # -------- Envoi email Mailjet (à activer quand mailing.py est prêt) --------
            # try:
            #     firstname = (name.split(" ")[0] if name else "")
            #     send_ambassador_welcome_email(email, firstname, code)
            # except Exception:
            #     app.logger.exception("Erreur envoi email Mailjet (inscription ambassadeur)")
            # -------------------------------------------------------------------------

            return redirect(url_for("dashboard", code=code))

    return render_template("inscription.html", error=error)


@app.route("/dashboard")
def dashboard():
    code = (request.args.get("code") or request.args.get("ref") or "").strip().upper()
    email = (request.args.get("email") or "").strip().lower()

    with closing(get_db()) as conn:
        ambassador = None

        if code:
            ambassador = conn.execute(
                "SELECT * FROM ambassadors WHERE code = ?",
                (code,),
            ).fetchone()
        elif email:
            ambassador = conn.execute(
                "SELECT * FROM ambassadors WHERE email = ?",
                (email,),
            ).fetchone()

        if not ambassador:
            return render_template(
                "dashboard.html",
                ambassador=None,
                stats=None,
                not_found=True,
            )

        clicks = int(ambassador["clicks"])
        signups = int(ambassador["signups"])

        # Estimations (comme tes pages)
        price = 79.90
        upfront_per = 0.30 * price
        recurring_per_month = 10.0

        est_upfront_total = signups * upfront_per
        est_monthly_recurring = signups * recurring_per_month
        est_6m_total = signups * (upfront_per + recurring_per_month * 6)

        # Liens
        short_link = url_for("redirect_with_ref", code=ambassador["code"], _external=True)
        tracking_link = short_link  # on privilégie le shortlink pour compter les clics

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
        ambassador = conn.execute(
            "SELECT * FROM ambassadors WHERE code = ?",
            (code,),
        ).fetchone()

        ref_code = code
        if ambassador:
            conn.execute(
                "UPDATE ambassadors SET clicks = clicks + 1 WHERE id = ?",
                (ambassador["id"],),
            )
            conn.commit()
            ref_code = ambassador["code"]

    target = f"https://www.spectramedia.online/?ref={ref_code}"
    return redirect(target)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
