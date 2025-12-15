# Betty Ambassadeur Dashboard

Mini-application Flask permettant aux ambassadeurs de la marque **Betty Bot** de :

- s'inscrire comme vendeur (ambassadeur),
- obtenir un lien unique de tracking,
- accéder à un tableau de bord affichant leurs ventes et commissions.

## Fonctionnement général

1. L'ambassadeur s'inscrit sur `/inscription`.
2. L'app génère un `ref_code` unique et enregistre l'ambassadeur en base.
3. Un lien vers son dashboard est généré : `/dashboard?ref=XXXX`.
4. Tu peux relier Stripe (webhooks) à la table `sales` pour alimenter les ventes.
5. L'ambassadeur voit ses ventes et ses commissions estimées sur son dashboard.

## Installation

```bash
git clone <URL_DU_REPO>
cd betty_ambassadeur_dashboard

python3 -m venv venv
source venv/bin/activate  # sous Windows: venv\\Scripts\\activate

pip install flask
sqlite3 database/betty.db < database/schema.sql

python app.py
