import os
import sqlite3
import secrets
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
)
import stripe

# -------------------------------------------------------------------
# Configuration de base
# -------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change_me_en_valeur_secret")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "betty.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")

# URL de base de la page d’abonnement Betty (le site public)
# -> c’est ici qu’on met spectramedia.online par défaut
BETTY_SIGNUP_BASE_URL = os.getenv(
    "BETTY_SIGNUP_BASE_URL",
    "https://www.spectramedia.online/"
)

# Config Stripe (optionnel, pour automatismes plus tard)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


# -------------------------------------------------------------------
# Utilitaires base de données
# -------------------------------------------------------------------

def get_db_connection():
    """Ouvre une connexion SQLite avec accès par nom de colonne."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crée la base de données à partir de schema.sql si betty.db n'existe pas."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)

    if not os.path.exists(DB_PATH):
        print("Initialisation de la base de données...")
        conn = sqlite3.connect(DB_PATH)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        print("Base de données créée.")


def generate_unique_ref_code(conn, length_bytes: int = 4) -> str:
    """Génère un ref_code unique non présent dans la table ambassadors."""
    while True:
        ref_code = secrets.token_urlsafe(length_bytes)
        row = conn.execute(
            "SELECT id FROM ambassadors WHERE ref_code = ?",
            (ref_code,),
        ).fetchone()
        if row is None:
            return ref_code


# -------------------------------------------------------------------
# Hooks Flask
# -------------------------------------------------------------------

@app.before_first_request
def before_first_request():
    """S'assure que la base est prête avant la première requête."""
    init_db()


# -------------------------------------------------------------------
# Routes principales
# -------------------------------------------------------------------

@app.route("/")
def index():
    """Redirige simplement vers l'inscription ambassadeur."""
    return redirect(url_for("inscription"))


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    """
    Formulaire d'inscription ambassadeur.

    - GET : affiche le formulaire
    - POST : enregistre l'ambassadeur + génère son lien dashboard.
    """
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        payout_method = request.form.get("payout_method", "").strip()
        payout_details = request.form.get("payout_details", "").strip()

        if not name or not email or not payout_method or not payout_details:
            flash("Tous les champs sont obligatoires.", "error")
            return render_template("inscription.html", link=None)

        # Génère un ref_code unique
        ref_code = generate_unique_ref_code(conn)

        try:
            conn.execute(
                """
                INSERT INTO ambassadors (name, email, payout_method, payout_details, ref_code)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, email, payout_method, payout_details, ref_code),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # email déjà utilisé par un ambassadeur : on récupère son ref_code existant
            flash("Cet email est déjà inscrit comme ambassadeur.", "error")
            row = conn.execute(
                "SELECT ref_code FROM ambassadors WHERE email = ?",
                (email,),
            ).fetchone()
            if row:
                ref_code = row["ref_code"]

        # Lien direct vers le dashboard
        dashboard_link = url_for("dashboard", ref=ref_code, _external=True)
        return render_template("inscription.html", link=dashboard_link)

    # GET
    return render_template("inscription.html", link=None)


@app.route("/dashboard")
def dashboard():
    """
    Dashboard ambassadeur : /dashboard?ref=XXXX

    Affiche :
    - infos ambassadeur
    - ventes (sales)
    - total des commissions estimées (30% des ventes payées)
    - le lien complet à partager (BETTY_SIGNUP_BASE_URL + ?ref=XXXX)
    """
    ref_code = request.args.get("ref", "").strip()
    if not ref_code:
        return "Lien invalide (ref manquant).", 400

    conn = get_db_connection()

    ambassador = conn.execute(
        "SELECT * FROM ambassadors WHERE ref_code = ?",
        (ref_code,),
    ).fetchone()

    if ambassador is None:
        return "Ambassadeur inconnu.", 404

    ventes = conn.execute(
        "SELECT * FROM sales WHERE ambassador_id = ? ORDER BY date DESC",
        (ambassador["id"],),
    ).fetchall()

    nb_ventes = len(ventes)
    nb_payees = sum(1 for v in ventes if v["paid"])
    nb_en_attente = nb_ventes - nb_payees

    # Total commissions = 30% des ventes payées
    total_commissions = sum(
        (v["amount"] * 0.30) / 100 for v in ventes if v["paid"]
    )

    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Lien à partager : page Betty Abo + ?ref=XXXX
    share_link = f"{BETTY_SIGNUP_BASE_URL}?ref={ref_code}"

    return render_template(
        "dashboard.html",
        ambassador=ambassador,
        ventes=ventes,
        nb_ventes=nb_ventes,
        nb_payees=nb_payees,
        nb_en_attente=nb_en_attente,
        total=round(total_commissions, 2),
        now=now,
        ref=ref_code,
        share_link=share_link,
    )


# -------------------------------------------------------------------
# (Optionnel) endpoint webhook Stripe à brancher plus tard
# -------------------------------------------------------------------

# @app.route("/stripe/webhook", methods=["POST"])
# def stripe_webhook():
#     """Exemple de point d'entrée Stripe pour alimenter la table sales."""
#     payload = request.data
#     sig_header = request.headers.get("Stripe-Signature", "")
#
#     try:
#         event = stripe.Webhook.construct_event(
#             payload, sig_header, STRIPE_WEBHOOK_SECRET
#         )
#     except Exception as e:
#         print("Webhook error:", e)
#         return "Bad payload", 400
#
#     # Ici tu traites l'événement (checkout.session.completed, invoice.paid, etc.)
#     # et tu insères dans la table `sales` la vente correspondant à un ref_code.
#     #
#     # À faire plus tard pour l’automatisation complète.
#
#     return "ok", 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
