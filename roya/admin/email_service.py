import json
from uuid import uuid4

from flask import current_app

from roya.common.db import db_connection
from roya.common.errors import RoyaError
from roya.notifications.service import NotificationService


AUDIENCE_ACCOUNT_TYPE = {
    "registered_guests": "guest",
    "registered_hotels": "hotel",
}


def _dict(row):
    return dict(row) if row else None


def list_templates():
    with db_connection() as conn:
        rows=conn.execute(
            """select id,name,subject,body,category,is_active,created_at,updated_at
               from private.email_templates
               where is_active=true
               order by name asc"""
        ).fetchall()
    return [dict(row) for row in rows]


def recent_campaigns(limit=8):
    with db_connection() as conn:
        rows=conn.execute(
            """select c.id,c.audience,c.subject,c.requested_recipients,c.queued_recipients,
                      c.created_at,t.name template_name,
                      count(n.id) filter (where n.status='sent') sent_recipients,
                      count(n.id) filter (where n.status='queued') queued_now,
                      count(n.id) filter (where n.status='failed') failed_recipients
               from private.email_campaigns c
               left join private.email_templates t on t.id=c.template_id
               left join public.notifications n
                 on n.channel='email'
                and n.payload->>'campaign_id'=c.id::text
               group by c.id,t.name
               order by c.created_at desc
               limit %s""",
            (max(1,min(int(limit),25)),),
        ).fetchall()
    return [dict(row) for row in rows]


def create_template(*,name,subject,body,category,actor_user_id):
    with db_connection() as conn:
        try:
            row=conn.execute(
                """insert into private.email_templates(
                     name,subject,body,category,created_by,updated_by
                   ) values(%s,%s,%s,%s,%s,%s)
                   returning id,name,subject,body,category,is_active,created_at,updated_at""",
                (name,subject,body,category,actor_user_id,actor_user_id),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,'email_template.created','email_template',%s,%s::jsonb)""",
                (actor_user_id,str(row["id"]),json.dumps({
                    "name":name,"category":category,"subject":subject,
                })),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "idx_email_templates_name_ci" in str(exc) or "duplicate key" in str(exc).lower():
                raise RoyaError(
                    "EMAIL_TEMPLATE_EXISTS",
                    "A template with this name already exists.",
                    409,
                ) from exc
            raise
    return dict(row)


def update_template(*,template_id,name,subject,body,category,actor_user_id):
    with db_connection() as conn:
        before=conn.execute(
            """select id,name,subject,category from private.email_templates
               where id=%s and is_active=true""",
            (template_id,),
        ).fetchone()
        if not before:
            raise RoyaError("EMAIL_TEMPLATE_NOT_FOUND","Email template not found.",404)
        try:
            row=conn.execute(
                """update private.email_templates
                   set name=%s,subject=%s,body=%s,category=%s,updated_by=%s,updated_at=now()
                   where id=%s
                   returning id,name,subject,body,category,is_active,created_at,updated_at""",
                (name,subject,body,category,actor_user_id,template_id),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,'email_template.updated','email_template',%s,%s::jsonb,%s::jsonb)""",
                (
                    actor_user_id,str(template_id),
                    json.dumps(dict(before),default=str),
                    json.dumps({"name":name,"category":category,"subject":subject}),
                ),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "idx_email_templates_name_ci" in str(exc) or "duplicate key" in str(exc).lower():
                raise RoyaError(
                    "EMAIL_TEMPLATE_EXISTS",
                    "A template with this name already exists.",
                    409,
                ) from exc
            raise
    return dict(row)


def delete_template(*,template_id,actor_user_id):
    with db_connection() as conn:
        row=conn.execute(
            """update private.email_templates
               set is_active=false,updated_by=%s,updated_at=now()
               where id=%s and is_active=true
               returning id,name""",
            (actor_user_id,template_id),
        ).fetchone()
        if not row:
            raise RoyaError("EMAIL_TEMPLATE_NOT_FOUND","Email template not found.",404)
        conn.execute(
            """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
               values(%s,'email_template.archived','email_template',%s,%s::jsonb)""",
            (actor_user_id,str(template_id),json.dumps({"name":row["name"]})),
        )
        conn.commit()
    return {"id":str(row["id"]),"archived":True}


def _personalize(text,*,name,email):
    value=text
    replacements={
        "{{name}}":(name or "there").strip() or "there",
        "{{email}}":email,
        "{{iroya_url}}":(current_app.config.get("APP_URL") or "").rstrip("/"),
    }
    for token,replacement in replacements.items():
        value=value.replace(token,replacement)
    return value


def _registered_recipients(conn,audience):
    account_type=AUDIENCE_ACCOUNT_TYPE.get(audience)
    params=[]
    where=["u.email is not null","u.email<>''"]
    if account_type:
        where.append("p.account_type=%s")
        params.append(account_type)
    rows=conn.execute(
        f"""select u.id user_id,lower(u.email) email,coalesce(p.name,'') name
            from auth.users u
            left join public.profiles p on p.user_id=u.id
            where {' and '.join(where)}
            order by u.created_at asc
            limit 5000""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def queue_campaign(
    *,
    audience,
    subject,
    body,
    actor_user_id,
    custom_recipients=None,
    template_id=None,
):
    if audience not in {"registered_all","registered_guests","registered_hotels","custom"}:
        raise RoyaError("VALIDATION_ERROR","Choose a valid email audience.",422)

    campaign_id=str(uuid4())
    queued_ids=[]
    recipients=[]

    with db_connection() as conn:
        with conn.transaction():
            if audience=="custom":
                seen=set()
                for email in custom_recipients or []:
                    normalized=str(email).strip().lower()
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        recipients.append({"user_id":None,"email":normalized,"name":""})
            else:
                recipients=_registered_recipients(conn,audience)

            if not recipients:
                raise RoyaError("NO_EMAIL_RECIPIENTS","No recipients matched this audience.",422)

            if len(recipients)>5000:
                raise RoyaError(
                    "EMAIL_AUDIENCE_TOO_LARGE",
                    "This campaign exceeds the current 5,000-recipient safety limit.",
                    422,
                )

            conn.execute(
                """insert into private.email_campaigns(
                     id,template_id,audience,subject,body,requested_recipients,created_by
                   ) values(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    campaign_id,
                    str(template_id) if template_id else None,
                    audience,
                    subject,
                    body,
                    len(recipients),
                    actor_user_id,
                ),
            )

            for recipient in recipients:
                personalized_subject=_personalize(
                    subject,name=recipient["name"],email=recipient["email"]
                )
                personalized_body=_personalize(
                    body,name=recipient["name"],email=recipient["email"]
                )
                row=conn.execute(
                    """insert into public.notifications(
                         user_id,reservation_id,channel,event_type,recipient,status,payload,next_attempt_at
                       ) values(%s,null,'email','marketing.campaign',%s,'queued',%s::jsonb,now())
                       returning id""",
                    (
                        recipient["user_id"],
                        recipient["email"],
                        json.dumps({
                            "campaign_id":campaign_id,
                            "template_id":str(template_id) if template_id else None,
                            "subject":personalized_subject,
                            "body":personalized_body,
                            "href":"/",
                        }),
                    ),
                ).fetchone()
                queued_ids.append(str(row["id"]))

            conn.execute(
                """update private.email_campaigns
                   set queued_recipients=%s
                   where id=%s""",
                (len(queued_ids),campaign_id),
            )
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,'email_campaign.queued','email_campaign',%s,%s::jsonb)""",
                (
                    actor_user_id,
                    campaign_id,
                    json.dumps({
                        "audience":audience,
                        "template_id":str(template_id) if template_id else None,
                        "queued_recipients":len(queued_ids),
                        "subject":subject,
                    }),
                ),
            )

    immediate_ids=queued_ids[:25]
    delivery=NotificationService().deliver_pending_emails(
        limit=len(immediate_ids) or 1,
        notification_ids=immediate_ids,
    ) if immediate_ids else {
        "configured":False,"checked":0,"sent":0,"retrying":0,"failed":0,
    }

    return {
        "campaign_id":campaign_id,
        "audience":audience,
        "queued":len(queued_ids),
        "immediate_delivery":delivery,
        "remaining_queued":max(len(queued_ids)-int(delivery.get("sent",0)),0),
    }


def deliver_email_queue(limit=100):
    return NotificationService().deliver_pending_emails(
        limit=max(1,min(int(limit),200))
    )
