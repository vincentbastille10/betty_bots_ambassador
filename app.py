import os
import sqlite3
import secrets
import datetime

from flask import Flask, render_template, request, redirect, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "betty.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# --------------------
# BDD
# --------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.join(BASE_DIR, "database"), exist_ok=True)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ambassadors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
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
    conn.close()


init_db()


def generate_code():
    """
    Génère un petit code ambassadeur lisible (6 caractères).
    """
    for _ in range(10):
        candidate = secrets.token_urlsafe(4)[:6]
        candidate = candidate.replace("-", "A").replace("_", "B")
        conn = get_db()
        row = conn.execute(
            "SELECT 1 FROM ambassadors WHERE code = ?", (candidate,)
        ).fetchone()
        conn.close()
        if not row:
            return candidate
    raise RuntimeError("Impossible de générer un code ambassadeur unique.")


# --------------------
# Routes
# --------------------
@app.route("/")
def index():
    # Redirige directement vers l’inscription ambassadeur
    return redirect(url_for("inscription"))


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    error = None

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        payout_preference = (request.form.get("payout_preference") or "").strip()
        payout_identifier = (request.form.get("payout_identifier") or "").strip()

        # Pas de case à cocher dans le template, donc on ne teste que ces champs
        if not name or not email or not payout_preference or not payout_identifier:
            error = (
                "Merci de remplir tous les champs obligatoires "
                "pour rejoindre le programme ambassadeur."
            )
        else:
            conn = get_db()
            # Si l'email existe déjà, on réutilise le même compte
            existing = conn.execute(
                "SELECT code FROM ambassadors WHERE email = ?", (email,)
            ).fetchone()

            if existing:
                code = existing["code"]
            else:
                code = generate_code()
                now = datetime.datetime.utcnow().isoformat()
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

            conn.close()

            # 🔁 Après inscription, on envoie l’ambassadeur sur son dashboard
            return redirect(url_for("dashboard", code=code))

    return render_template("inscription.html", error=error)


@app.route("/dashboard")
def dashboard():
    # Compatibilité : accepte ?code=... ou ?ref=...
    code = (request.args.get("code") or request.args.get("ref") or "").strip()
    email = (request.args.get("email") or "").strip().lower()

    conn = get_db()
    ambassador = None

    if code:
        ambassador = conn.execute(
            "SELECT * FROM ambassadors WHERE code = ?", (code,)
        ).fetchone()
    elif email:
        ambassador = conn.execute(
            "SELECT * FROM ambassadors WHERE email = ?", (email,)
        ).fetchone()

    if not ambassador:
        conn.close()
        # Dashboard "vide" avec message doux (templates/dashboard.html gère le cas ambassador=None)
        return render_template(
            "dashboard.html",
            ambassador=None,
            stats=None,
            not_found=True,
        )

    # Statistiques de base depuis la BDD
    clicks = ambassador["clicks"]
    signups = ambassador["signups"]

    # Hypothèses pour l’estimation (cohérent avec ce qu’on affiche dans les pages)
    price = 79.90
    upfront_per = 0.30 * price      # 30 % de 79,90 €
    recurring_per_month = 10.0      # 10 € / mois / abonnement

    est_upfront_total = signups * upfront_per
    est_monthly_recurring = signups * recurring_per_month
    est_6m_total = signups * (upfront_per + recurring_per_month * 6)

    # Lien vers la page Betty avec ?ref=CODE (à partager aux clients)
    tracking_link = f"https://www.spectramedia.online/?ref={ambassador['code']}"
    # Lien court optionnel (si tu veux l’afficher quelque part plus tard)
    short_link = url_for("redirect_with_ref", code=ambassador["code"], _external=True)

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

    conn.close()

    # Les variables utilisées par dashboard.html :
    #  - ambassador
    #  - betty_link : lien à partager (vers spectramedia.online/?ref=CODE)
    #  - total_sales : nombre d’abonnements générés
    #  - total_clicks : nombre de clics sur le lien
    #  - total_commission : estimation globale sur 6 mois (pour affichage simple)
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
    """
    Lien court pour les ambassadeurs.
    Incrémente les clics, puis redirige vers spectramedia.online avec ?ref=CODE.
    """
    conn = get_db()
    ambassador = conn.execute(
        "SELECT * FROM ambassadors WHERE code = ?", (code,)
    ).fetchone()

    if ambassador:
        conn.execute(
            "UPDATE ambassadors SET clicks = clicks + 1 WHERE id = ?",
            (ambassador["id"],),
        )
        conn.commit()
        ref_code = ambassador["code"]
    else:
        # Si le code n’existe pas en BDD, on redirige quand même avec ce code brut
        ref_code = code

    conn.close()

    target = f"https://www.spectramedia.online/?ref={ref_code}"
    return redirect(target)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
