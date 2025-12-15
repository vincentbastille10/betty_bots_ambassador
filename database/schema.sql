-- Table des ambassadeurs
CREATE TABLE IF NOT EXISTS ambassadors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE NOT NULL,
    ref_code TEXT UNIQUE NOT NULL,
    iban TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table des ventes générées par chaque ambassadeur
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ambassador_id INTEGER NOT NULL,
    customer_email TEXT,
    amount INTEGER NOT NULL,            -- montant en centimes (ex: 7900 = 79.00€)
    subscription_id TEXT,               -- id abonnement Stripe, optionnel
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid INTEGER DEFAULT 0,             -- 0 = en attente / 1 = payé
    FOREIGN KEY (ambassador_id) REFERENCES ambassadors(id)
);
