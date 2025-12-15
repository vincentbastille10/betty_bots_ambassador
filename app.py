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
    abort
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

# URL de base de la page d’abonnement Betty (à adapter si besoin)
BETTY_SIGNUP_BASE_URL = os.getenv(
    "BETTY_SIGNUP_BASE_URL",
    "https://betty-bots.vercel.app/abo"
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
            (ref_code,)
        ).fetchone()
        if row is None:
            return ref_code


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
        iban = request.form.get("iban", "").strip()

        if not name or not email or not iban:
            flash("Tous les champs sont obligatoires.", "error")
            return render_template("inscription.html", link=None)

        # Génère ref_code unique
        ref_code = generate_unique_ref_code(conn)

        try:
            conn.execute(
                """
                INSERT INTO ambassadors (name, email, iban, ref_code)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, iban, ref_code),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # email déjà utilisé par un ambassadeur
            flash("Cet email est déjà inscrit comme ambassadeur.", "error")
            row = conn.execute(
                "SELECT ref_code FROM ambassadors WHERE email = ?",
                (email,)
            ).fetchone()
            if row:
                ref_code = row["ref_code"]

        dashboard_link = url_for("dashboard", ref=ref_code, _external=True)
        return render_template("inscription.html", link=dashboard_link)

    return render_template("inscription.html", link=None)


@app.route("/dashboard")
def dashboard():
    """
    Dashboard ambassadeur : /dashboard?ref=XXXX
    Affiche :
    - infos ambassadeur
    - ventes (sales)
    - total des commissions estimées
    - le lien complet à partager (page Betty Abo + ?ref=XXXX)
    """
    ref_code = request.args.get("ref", "").strip()

    if not ref_code:
        return "Lien invalide (ref manquant).", 400

    conn = get_db_connection()

    ambassador = conn.execute(
        "SELECT * FROM ambassadors WHERE ref_code = ?",
        (ref_code,)
    ).fetchone()

    if ambassador is None:
        return "Ambassadeur inconnu. Vérifie ton lien.", 404

    ventes = conn.execute(
        """
        SELECT *
        FROM sales
        WHERE ambassador_id = ?
        ORDER BY date DESC
        """,
        (ambassador["id"],)
    ).fetchall()

    total_commissions_cents = 0
    for v in ventes:
        commission_for_sale = int(v["amount"] * 0.30)
        total_commissions_cents += commission_for_sale

    total_commissions_euros = round(total_commissions_cents / 100, 2)

    nb_ventes = len(ventes)
    nb_payees = len([v for v in ventes if v["paid"] == 1])
    nb_en_attente = nb_ventes - nb_payees

    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    # Lien complet à partager par l'ambassadeur
    share_link = f"{BETTY_SIGNUP_BASE_URL}?ref={ref_code}"

    return render_template(
        "dashboard.html",
        ref=ref_code,
        ambassador=ambassador,
        ventes=ventes,
        total=total_commissions_euros,
        nb_ventes=nb_ventes,
        nb_payees=nb_payees,
        nb_en_attente=nb_en_attente,
        now=now_str,
        share_link=share_link,
    )


# -------------------------------------------------------------------
# Webhook Stripe (optionnel, MVP : peut rester inactif)
# -------------------------------------------------------------------

@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """
    Webhook Stripe pour automatiser les ventes.
    Si STRIPE_WEBHOOK_SECRET n'est pas défini, on ignore.
    """
    if not STRIPE_WEBHOOK_SECRET:
        return "webhook désactivé (pas de secret)", 200

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET
        )
    except Exception:
        abort(400)

    event_type = event["type"]
    data_object = event["data"]["object"]

    conn = get_db_connection()

    # Exemple minimal : première vente
    if event_type == "checkout.session.completed":
        session = data_object
        ref = (session.get("metadata") or {}).get("ref")
        customer_email = session.get("customer_details", {}).get("email")
        subscription_id = session.get("subscription")
        customer_id = session.get("customer")
        amount_total = session.get("amount_total") or 0

        if not ref:
            return "ok", 200

        ambassador = conn.execute(
            "SELECT * FROM ambassadors WHERE ref_code = ?",
            (ref,)
        ).fetchone()

        if ambassador is None:
            return "ok", 200

        conn.execute(
            """
            INSERT INTO sales (
                ambassador_id,
                customer_email,
                amount,
                subscription_id,
                stripe_customer_id,
                stripe_invoice_id,
                source,
                paid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ambassador["id"],
                customer_email,
                amount_total,
                subscription_id,
                customer_id,
                None,
                "initial",
                0
            ),
        )
        conn.commit()
        return "ok", 200

    # Renouvellements (invoice.paid) – à compléter plus tard
    if event_type == "invoice.paid":
        return "ok", 200

    return "ignored", 200


# -------------------------------------------------------------------
# Route d'admin pour ajouter manuellement des ventes (MVP)
# -------------------------------------------------------------------

@app.route("/admin/add_sale", methods=["GET", "POST"])
def admin_add_sale():
    """
    Petite interface HTML pour ajouter une vente à la main.
    Utile au début avant d'automatiser Stripe.
    À sécuriser ou supprimer en production.
    """
    conn = get_db_connection()

    if request.method == "POST":
        ambassador_id = request.form.get("ambassador_id")
        customer_email = request.form.get("customer_email", "").strip().lower()
        amount_euros_raw = request.form.get("amount_euros", "0").replace(",", ".")
        try:
            amount_euros = float(amount_euros_raw)
        except ValueError:
            amount_euros = 0.0

        subscription_id = request.form.get("subscription_id", "").strip()
        paid_flag = 1 if request.form.get("paid") == "on" else 0

        amount_cents = int(amount_euros * 100)

        conn.execute(
            """
            INSERT INTO sales (
                ambassador_id,
                customer_email,
                amount,
                subscription_id,
                stripe_customer_id,
                stripe_invoice_id,
                source,
                paid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ambassador_id,
                customer_email,
                amount_cents,
                subscription_id,
                None,
                None,
                "manual",
                paid_flag,
            ),
        )
        conn.commit()

        flash("Vente ajoutée.", "success")
        return redirect(url_for("admin_add_sale"))

    ambassadors = conn.execute(
        "SELECT id, name, email, ref_code FROM ambassadors ORDER BY created_at DESC"
    ).fetchall()

    options_html = "\n".join(
        f'<option value="{a["id"]}">{a["name"]} ({a["email"]}) - ref={a["ref_code"]}</option>'
        for a in ambassadors
    )

    return f"""
    <h1>Admin - Ajouter une vente</h1>
    <form method="POST">
      <label>Ambassadeur :</label><br>
      <select name="ambassador_id">
        {options_html}
      </select><br><br>

      <label>Email client :</label><br>
      <input name="customer_email"><br><br>

      <label>Montant (en euros) :</label><br>
      <input name="amount_euros" value="79"><br><br>

      <label>ID abonnement Stripe (optionnel) :</label><br>
      <input name="subscription_id"><br><br>

      <label>Payé ?</label>
      <input type="checkbox" name="paid"><br><br>

      <button type="submit">Enregistrer</button>
    </form>
    """


# -------------------------------------------------------------------
# Lancement
# -------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
