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
    flash
)

# -------------------------------------------------------------------
# Configuration de base
# -------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = "change_me_en_valeur_secret"  # pour flash() si besoin

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "betty.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


# -------------------------------------------------------------------
# Utilitaires base de données
# -------------------------------------------------------------------

def get_db_connection():
    """
    Ouvre une connexion SQLite avec row_factory pour accès par nom de colonne.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Crée la base de données à partir du fichier schema.sql si betty.db n'existe pas.
    """
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)

    db_exists = os.path.exists(DB_PATH)

    if not db_exists:
        print("Initialisation de la base de données...")
        conn = sqlite3.connect(DB_PATH)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        print("Base de données créée.")


def generate_unique_ref_code(conn, length_bytes: int = 4) -> str:
    """
    Génère un ref_code unique non présent dans la table ambassadors.
    length_bytes = nombre d'octets pour token_urlsafe.
    """
    while True:
        ref_code = secrets.token_urlsafe(length_bytes)  # ex: 'a8xH2Kjd'
        row = conn.execute(
            "SELECT id FROM ambassadors WHERE ref_code = ?",
            (ref_code,)
        ).fetchone()
        if row is None:
            return ref_code


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@app.route("/")
def index():
    """
    Page d'accueil simple : redirige vers l'inscription ambassadeur.
    Dans ton écosystème, cette page peut être remplacée par
    un message explicatif ou un lien depuis Betty Abo.
    """
    return redirect(url_for("inscription"))


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    """
    Formulaire d'inscription ambassadeur.
    - GET : affiche le formulaire
    - POST : enregistre l'ambassadeur, génère le ref_code,
      affiche le lien de tracking + accès dashboard.
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
            # On récupère son ref_code existant pour lui renvoyer son lien
            row = conn.execute(
                "SELECT ref_code FROM ambassadors WHERE email = ?",
                (email,)
            ).fetchone()
            if row:
                ref_code = row["ref_code"]

        # Lien vers le dashboard pour cet ambassadeur
        dashboard_link = url_for("dashboard", ref=ref_code, _external=True)

        return render_template("inscription.html", link=dashboard_link)

    # GET
    return render_template("inscription.html", link=None)


@app.route("/dashboard")
def dashboard():
    """
    Dashboard ambassadeur, accessible via un lien :
    /dashboard?ref=XXXX

    Pour un vrai niveau pro plus tard, tu pourras ajouter :
      - email + code de connexion
      - mot de passe
      - JWT, etc.
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

    # Calcul simple : 30% du montant pour chaque vente
    total_commissions_cents = 0
    for v in ventes:
        # v["amount"] en centimes
        commission_for_sale = int(v["amount"] * 0.30)
        total_commissions_cents += commission_for_sale

    total_commissions_euros = round(total_commissions_cents / 100, 2)

    # Statistiques simples
    nb_ventes = len(ventes)
    nb_payees = len([v for v in ventes if v["paid"] == 1])
    nb_en_attente = nb_ventes - nb_payees

    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    return render_template(
        "dashboard.html",
        ref=ref_code,
        ambassador=ambassador,
        ventes=ventes,
        total=total_commissions_euros,
        nb_ventes=nb_ventes,
        nb_payees=nb_payees,
        nb_en_attente=nb_en_attente,
        now=now_str
    )


# -------------------------------------------------------------------
# (Optionnel) Route d'admin ultra simple pour ajouter une vente à la main
# -------------------------------------------------------------------

@app.route("/admin/add_sale", methods=["GET", "POST"])
def admin_add_sale():
    """
    Route d'admin pour ajouter une vente manuellement (pour tests ou
    pour enregistrer un paiement Stripe sans encore coder le webhook).
    PROVISOIRE, à sécuriser ou à supprimer en prod.
    """
    conn = get_db_connection()

    if request.method == "POST":
        ambassador_id = request.form.get("ambassador_id")
        customer_email = request.form.get("customer_email", "").strip().lower()
        amount_euros = float(request.form.get("amount_euros", "0").replace(",", "."))
        subscription_id = request.form.get("subscription_id", "").strip()
        paid_flag = 1 if request.form.get("paid") == "on" else 0

        amount_cents = int(amount_euros * 100)

        conn.execute(
            """
            INSERT INTO sales (ambassador_id, customer_email, amount, subscription_id, paid)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ambassador_id, customer_email, amount_cents, subscription_id, paid_flag),
        )
        conn.commit()

        flash("Vente ajoutée.", "success")
        return redirect(url_for("admin_add_sale"))

    ambassadors = conn.execute(
        "SELECT id, name, email, ref_code FROM ambassadors ORDER BY created_at DESC"
    ).fetchall()

    return """
    <h1>Admin - Ajouter une vente</h1>
    <form method="POST">
      <label>Ambassadeur :</label><br>
      <select name="ambassador_id">
        {options}
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
    """.format(
        options="\n".join(
            f'<option value="{a["id"]}">{a["name"]} ({a["email"]}) - ref={a["ref_code"]}</option>'
            for a in ambassadors
        )
    )


# -------------------------------------------------------------------
# Lancement de l'application
# -------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    # host="0.0.0.0" pour Render/serveur
    app.run(debug=True, host="0.0.0.0", port=5000)
