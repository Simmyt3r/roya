from flask import Blueprint,render_template

from roya.auth.service import current_identity,login_required
from roya.common.errors import RoyaError
from roya.common.response import ok
from .service import NotificationService

bp=Blueprint("notifications",__name__)
service=NotificationService()


@bp.get("/notifications")
@login_required
def notification_page():
    identity=current_identity(required=True)
    notifications=service.list_for_user(identity.user_id)
    unread=sum(1 for item in notifications if item["read_at"] is None)
    return render_template("notifications/index.html",notifications=notifications,unread=unread)


@bp.post("/api/v1/notifications/<uuid:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    identity=current_identity(required=True)
    row=service.mark_read(identity.user_id,str(notification_id))
    if not row:
        raise RoyaError("NOTIFICATION_NOT_FOUND","Notification not found.",404)
    return ok(row)


@bp.post("/api/v1/notifications/read-all")
@login_required
def mark_all_notifications_read():
    identity=current_identity(required=True)
    return ok(service.mark_all_read(identity.user_id))
