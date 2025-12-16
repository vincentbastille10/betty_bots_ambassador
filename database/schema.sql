-- Table des ambassadeurs
CREATE TABLE IF NOT EXISTS ambassadors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    ref_code TEXT UNIQUE NOT NULL,
    payout_method TEXT NOT NULL,   -- ex: "Virement", "PayPal", "Autre"
    payout_details TEXT NOT NULL,  -- IBAN, email PayPal, lien Stripe, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des ventes générées par chaque ambassadeur
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ambassador_id INTEGER NOT NULL,
    customer_email TEXT,
    amount INTEGER NOT NULL,       -- montant en centimes (ex: 7990 = 79.90€)
    subscription_id TEXT,          -- id abonnement Stripe, optionnel
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid INTEGER DEFAULT 0,        -- 0 = en attente / 1 = payé
    FOREIGN KEY (ambassador_id) REFERENCES ambassadors(id)
);
