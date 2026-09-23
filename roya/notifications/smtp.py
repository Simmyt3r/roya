import smtplib
from email.message import EmailMessage
from flask import current_app
from .service import NotificationAdapter


class SmtpNotificationAdapter(NotificationAdapter):
    def send(self,*,recipient,subject,body):
        host=current_app.config.get("SMTP_HOST"); sender=current_app.config.get("SMTP_FROM")
        if not host or not sender:
            return {"sent":False,"reason":"smtp_not_configured"}
        msg=EmailMessage(); msg["From"]=sender; msg["To"]=recipient; msg["Subject"]=subject; msg.set_content(body)
        with smtplib.SMTP(host,int(current_app.config.get("SMTP_PORT",587)),timeout=10) as smtp:
            if current_app.config.get("SMTP_TLS",True): smtp.starttls()
            username=current_app.config.get("SMTP_USERNAME"); password=current_app.config.get("SMTP_PASSWORD")
            if username and password: smtp.login(username,password)
            smtp.send_message(msg)
        return {"sent":True}
