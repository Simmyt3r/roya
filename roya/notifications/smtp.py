import smtplib
import ssl
from email.message import EmailMessage
from roya.common.errors import RoyaError
from roya.common.integrations import smtp_settings
from .service import NotificationAdapter


class SmtpNotificationAdapter(NotificationAdapter):
    @staticmethod
    def _connect(settings):
        if not settings["host"] or not settings["sender"]:
            raise RoyaError("SMTP_NOT_CONFIGURED","SMTP is not configured.",503)
        if settings["security"]=="ssl":
            smtp=smtplib.SMTP_SSL(
                settings["host"],int(settings["port"]),timeout=10,
                context=ssl.create_default_context(),
            )
        else:
            smtp=smtplib.SMTP(settings["host"],int(settings["port"]),timeout=10)
        try:
            if settings["security"]=="starttls":
                smtp.starttls(context=ssl.create_default_context())
            if settings["username"] and settings["password"]:
                smtp.login(settings["username"],settings["password"])
            elif settings["username"]:
                raise RoyaError("SMTP_NOT_CONFIGURED","SMTP password is missing.",503)
            return smtp
        except Exception:
            smtp.close()
            raise

    def test_connection(self):
        settings=smtp_settings()
        try:
            with self._connect(settings):
                pass
        except RoyaError:
            raise
        except (OSError,smtplib.SMTPException) as exc:
            raise RoyaError(
                "SMTP_CONNECTION_FAILED",
                "SMTP connection or login failed. Check the host, port, encryption and credentials.",
                502,
            ) from exc

    def send(self,*,recipient,subject,body):
        settings=smtp_settings()
        if not settings["host"] or not settings["sender"]:
            return {"sent":False,"reason":"smtp_not_configured"}
        msg=EmailMessage(); msg["From"]=settings["sender"]; msg["To"]=recipient; msg["Subject"]=subject; msg.set_content(body)
        with self._connect(settings) as smtp:
            smtp.send_message(msg)
        return {"sent":True}
