from roya import create_app
from roya.notifications.service import NotificationService


def test_email_queue_skips_cleanly_when_smtp_is_not_configured():
    app=create_app({
        "TESTING":True,
        "WTF_CSRF_ENABLED":False,
        "SMTP_HOST":"",
        "SMTP_FROM":"",
    })
    with app.app_context():
        result=NotificationService().deliver_pending_emails(limit=10)
    assert result["configured"] is False
    assert result["checked"]==0
    assert result["sent"]==0
