import os
from mailjet_rest import Client

def send_ambassador_welcome_email(to_email: str, firstname: str, ref_code: str):
    api_key = os.getenv("MAILJET_API_KEY")
    api_secret = os.getenv("MAILJET_API_SECRET")
    from_email = os.getenv("MAIL_FROM_EMAIL", "spectramediabots@gmail.com")
    from_name = os.getenv("MAIL_FROM_NAME", "Betty Bots")
    reply_to = os.getenv("MAIL_REPLY_TO", from_email)
    base_url = os.getenv("APP_BASE_URL", "").rstrip("/")

    if not api_key or not api_secret:
        raise RuntimeError("MAILJET_API_KEY / MAILJET_API_SECRET manquants")
    if not base_url:
        raise RuntimeError("APP_BASE_URL manquant")

    dashboard_url = f"{base_url}/dashboard/{ref_code}"
    subject = "✅ Bienvenue chez les Ambassadeurs Betty Bots — votre lien personnel"

    text_part = (
        f"Bonjour {firstname},\n\n"
        "Bienvenue chez les Ambassadeurs Betty Bots 🎉\n\n"
        "Voici votre lien personnel (à conserver) :\n"
        f"{dashboard_url}\n\n"
        f"Votre code ambassadeur : {ref_code}\n\n"
        "Besoin d’aide ? Répondez simplement à ce mail.\n\n"
        "Vincent — Spectra Media AI\n"
    )

    html_part = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#0f172a">
      <h2 style="margin:0 0 10px">✅ Bienvenue chez les Ambassadeurs Betty Bots</h2>
      <p style="margin:0 0 14px">Bonjour <strong>{firstname}</strong>,</p>
      <p style="margin:0 0 14px">Voici votre lien personnel (à conserver) :</p>
      <p style="margin:0 0 18px">
        <a href="{dashboard_url}" style="display:inline-block;background:#7c3aed;color:#fff;text-decoration:none;padding:12px 16px;border-radius:12px">
          Ouvrir mon dashboard
        </a>
      </p>
      <p style="margin:0 0 18px"><strong>Votre code :</strong> {ref_code}</p>
      <p style="margin:0">Vincent — Spectra Media AI</p>
    </div>
    """

    mailjet = Client(auth=(api_key, api_secret), version="v3.1")
    data = {
        "Messages": [{
            "From": {"Email": from_email, "Name": from_name},
            "To": [{"Email": to_email, "Name": firstname or to_email}],
            "ReplyTo": {"Email": reply_to, "Name": from_name},
            "Subject": subject,
            "TextPart": text_part,
            "HTMLPart": html_part,
        }]
    }

    result = mailjet.send.create(data=data)
    if result.status_code >= 300:
        raise RuntimeError(f"Mailjet error {result.status_code}: {result.json()}")
    return result.json()
