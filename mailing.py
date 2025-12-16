import os
from mailjet_rest import Client

MAILJET_API_KEY = os.environ.get("MAILJET_API_KEY", "")
MAILJET_API_SECRET = os.environ.get("MAILJET_API_SECRET", "")
MAILJET_SENDER_EMAIL = os.environ.get("MAILJET_SENDER_EMAIL", "spectramediabots@gmail.com")
MAILJET_SENDER_NAME = os.environ.get("MAILJET_SENDER_NAME", "Betty Bots")


def send_ambassador_welcome_email(
    to_email: str,
    firstname: str,
    code: str,
    dashboard_url: str,
    short_link: str,
    tracking_target: str,
    is_new: bool = True,
):
    if not MAILJET_API_KEY or not MAILJET_API_SECRET:
        raise RuntimeError("MAILJET_API_KEY / MAILJET_API_SECRET manquantes")

    subject = "Votre lien Ambassadeur Betty Bot (dashboard + lien traqué)"
    if not is_new:
        subject = "Votre lien Ambassadeur Betty Bot (rappel)"

    hello = f"Bonjour {firstname}," if firstname else "Bonjour,"

    text_part = (
        f"{hello}\n\n"
        f"Voici votre accès Ambassadeur Betty Bot :\n\n"
        f"- Dashboard : {dashboard_url}\n"
        f"- Lien à partager (traqué) : {short_link}\n"
        f"- Cible finale : {tracking_target}\n"
        f"- Votre code : {code}\n\n"
        f"Gardez ce mail : il contient vos liens.\n"
        f"— Spectra Media AI\n"
    )

    html_part = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.5;color:#0f172a">
      <p>{hello}</p>
      <p>Voici votre accès <strong>Ambassadeur Betty Bot</strong> :</p>

      <div style="padding:12px;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc">
        <p style="margin:0 0 8px;"><strong>Dashboard</strong> :<br>
          <a href="{dashboard_url}">{dashboard_url}</a>
        </p>
        <p style="margin:0 0 8px;"><strong>Lien à partager (traqué)</strong> :<br>
          <a href="{short_link}">{short_link}</a>
        </p>
        <p style="margin:0 0 8px;"><strong>Cible finale</strong> :<br>
          <a href="{tracking_target}">{tracking_target}</a>
        </p>
        <p style="margin:0;"><strong>Votre code</strong> : <code>{code}</code></p>
      </div>

      <p style="margin-top:14px;">Gardez ce mail : il contient vos liens.</p>
      <p style="opacity:.75;margin-top:10px;">— Spectra Media AI</p>
    </div>
    """

    mailjet = Client(auth=(MAILJET_API_KEY, MAILJET_API_SECRET), version="v3.1")

    data = {
        "Messages": [
            {
                "From": {"Email": MAILJET_SENDER_EMAIL, "Name": MAILJET_SENDER_NAME},
                "To": [{"Email": to_email}],
                "Subject": subject,
                "TextPart": text_part,
                "HTMLPart": html_part,
            }
        ]
    }

    result = mailjet.send.create(data=data)
    if result.status_code >= 300:
        raise RuntimeError(f"Mailjet error {result.status_code}: {result.json()}")
    return result.json()
