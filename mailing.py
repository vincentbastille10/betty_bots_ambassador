import os
from mailjet_rest import Client


def _get_env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def send_ambassador_welcome_email(
    to_email: str,
    firstname: str,
    code: str,
    dashboard_url: str,
    short_link: str,
    tracking_target: str,  # conservé pour compatibilité (mais NON affiché)
    is_new: bool = True,
):
    """
    Envoie un email de confirmation (récap liens) à l'ambassadeur.
    Utilise les variables d'environnement Render:
      - MAILJET_API_KEY
      - MAILJET_API_SECRET
      - MAIL_FROM_EMAIL
      - MAIL_FROM_NAME
      - MAIL_REPLY_TO (optionnel)
    """

    api_key = _get_env("MAILJET_API_KEY")
    api_secret = _get_env("MAILJET_API_SECRET")

    mail_from_email = _get_env("MAIL_FROM_EMAIL", "no-reply@spectramedia.online")
    mail_from_name = _get_env("MAIL_FROM_NAME", "Betty Bots — Spectra Media")
    mail_reply_to = _get_env("MAIL_REPLY_TO", "no-reply@spectramedia.online")

    if not api_key or not api_secret:
        raise RuntimeError("MAILJET_API_KEY / MAILJET_API_SECRET manquantes")

    if not to_email:
        raise ValueError("to_email est vide")

    subject = "✅ Votre accès Ambassadeur Betty Bot (liens + dashboard)"
    if not is_new:
        subject = "🔁 Rappel — votre accès Ambassadeur Betty Bot"

    hello = f"Bonjour {firstname}," if firstname else "Bonjour,"

    # ✅ On n'affiche PLUS le lien final (tracking_target) pour éviter la confusion
    text_part = (
        f"{hello}\n\n"
        f"Bienvenue dans le programme Ambassadeurs Betty Bot.\n\n"
        f"Voici vos liens personnels (gardez ce mail) :\n"
        f"- Dashboard : {dashboard_url}\n"
        f"- Lien à partager (traqué) : {short_link}\n"
        f"- Votre code : {code}\n\n"
        f"— Spectra Media AI\n"
    )

    html_part = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.5;color:#0f172a">
      <p>{hello}</p>

      <p>
        Voici votre <strong>accès Ambassadeur Betty Bot</strong>.
        Gardez ce mail : il contient <strong>tous vos liens</strong>.
      </p>

      <div style="padding:14px;border:1px solid #e2e8f0;border-radius:14px;background:#f8fafc">
        <p style="margin:0 0 10px;">
          <strong>Dashboard</strong><br>
          <a href="{dashboard_url}" style="color:#2563eb">{dashboard_url}</a>
        </p>

        <p style="margin:0 0 10px;">
          <strong>Lien à partager (traqué)</strong><br>
          <a href="{short_link}" style="color:#2563eb">{short_link}</a>
        </p>

        <p style="margin:0;">
          <strong>Votre code</strong> : <code style="font-size:14px">{code}</code>
        </p>
      </div>

      <p style="margin-top:14px;">
        Besoin d’aide ? Répondez simplement à ce mail.
      </p>

      <p style="opacity:.7;margin-top:10px;">— Spectra Media AI</p>
    </div>
    """

    mailjet = Client(auth=(api_key, api_secret), version="v3.1")

    data = {
        "Messages": [
            {
                "From": {"Email": mail_from_email, "Name": mail_from_name},
                "ReplyTo": {"Email": mail_reply_to, "Name": mail_from_name},
                "To": [{"Email": to_email}],
                "Subject": subject,
                "TextPart": text_part,
                "HTMLPart": html_part,
            }
        ]
    }

    result = mailjet.send.create(data=data)

    # Si Mailjet refuse, on veut une erreur claire (et visible dans les logs Render)
    if result.status_code >= 300:
        raise RuntimeError(f"Mailjet error {result.status_code}: {result.json()}")

    return result.json()
