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


def list_templates():
    with db_connection() as conn:
        rows=conn.execute(
            """select id::text id,name,subject,body,category
               from private.marketing_templates
               where is_active=true
               order by name asc"""
        ).fetchall()
    return [dict(row) for row in rows]


def subscriber_counts():
    with db_connection() as conn:
        row=conn.execute(
            """select
                 count(*) filter (
                   where ms.consent_at is not null and ms.unsubscribed_at is null
                 ) active_total,
                 count(*) filter (
                   where ms.consent_at is not null and ms.unsubscribed_at is null
                     and u.id is not null
                 ) active_registered,
                 count(*) filter (
                   where ms.consent_at is not null and ms.unsubscribed_at is null
                     and u.id is null
                 ) active_external
               from private.marketing_subscribers ms
               left join auth.users u on lower(u.email)=lower(ms.email)"""
        ).fetchone()
    return {
        "active_total":int(row["active_total"] or 0),
        "active_registered":int(row["active_registered"] or 0),
        "active_external":int(row["active_external"] or 0),
    }


def recent_campaigns(limit=8):
    with db_connection() as conn:
        rows=conn.execute(
            """select c.id::text id,c.audience,c.subject,
                      c.requested_recipients,c.queued_recipients,
                      c.created_at,t.name template_name,
                      count(n.id) filter (where n.status='sent') sent_recipients,
                      count(n.id) filter (where n.status='queued') queued_now,
                      count(n.id) filter (where n.status='failed') failed_recipients
               from private.marketing_campaigns c
               left join private.marketing_templates t on t.id=c.template_id
               left join public.notifications n
                 on n.channel='email'
                and n.event_type='marketing.campaign'
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
                """insert into private.marketing_templates(
                     name,subject,body,category,created_by
                   ) values(%s,%s,%s,%s,%s)
                   returning id::text id,name,subject,body,category""",
                (name,subject,body,category,actor_user_id),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,'email_template.created','marketing_template',%s,%s::jsonb)""",
                (
                    actor_user_id,row["id"],
                    json.dumps({"name":name,"category":category,"subject":subject}),
                ),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "marketing_templates_name" in str(exc) or "duplicate key" in str(exc).lower():
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
            """select id::text id,name,subject,category
               from private.marketing_templates
               where id=%s and is_active=true""",
            (template_id,),
        ).fetchone()
        if not before:
            raise RoyaError("EMAIL_TEMPLATE_NOT_FOUND","Email template not found.",404)
        try:
            row=conn.execute(
                """update private.marketing_templates
                   set name=%s,subject=%s,body=%s,category=%s,updated_at=now()
                   where id=%s
                   returning id::text id,name,subject,body,category""",
                (name,subject,body,category,template_id),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,before_json,after_json)
                   values(%s,'email_template.updated','marketing_template',%s,%s::jsonb,%s::jsonb)""",
                (
                    actor_user_id,str(template_id),
                    json.dumps(dict(before),default=str),
                    json.dumps({"name":name,"category":category,"subject":subject}),
                ),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "marketing_templates_name" in str(exc) or "duplicate key" in str(exc).lower():
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
            """update private.marketing_templates
               set is_active=false,updated_at=now()
               where id=%s and is_active=true
               returning id::text id,name""",
            (template_id,),
        ).fetchone()
        if not row:
            raise RoyaError("EMAIL_TEMPLATE_NOT_FOUND","Email template not found.",404)
        conn.execute(
            """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
               values(%s,'email_template.archived','marketing_template',%s,%s::jsonb)""",
            (actor_user_id,row["id"],json.dumps({"name":row["name"]})),
        )
        conn.commit()
    return {"id":row["id"],"archived":True}


def record_marketing_consent(*,email,actor_user_id):
    normalized=email.strip().lower()
    with db_connection() as conn:
        with conn.transaction():
            user=conn.execute(
                """select id from auth.users where lower(email)=lower(%s) limit 1""",
                (normalized,),
            ).fetchone()
            user_id=str(user["id"]) if user else None
            row=conn.execute(
                """insert into private.marketing_subscribers(
                     email,user_id,consent_source,consent_at,unsubscribed_at
                   ) values(%s,%s,'admin_confirmed',now(),null)
                   on conflict (lower(email)) do update
                   set user_id=coalesce(excluded.user_id,marketing_subscribers.user_id),
                       consent_source='admin_confirmed',
                       consent_at=now(),
                       unsubscribed_at=null,
                       updated_at=now()
                   returning id::text id,email,user_id::text,consent_at""",
                (normalized,user_id),
            ).fetchone()
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,'marketing_consent.recorded','marketing_subscriber',%s,%s::jsonb)""",
                (
                    actor_user_id,row["id"],
                    json.dumps({
                        "email":normalized,
                        "linked_registered_user":bool(user_id),
                        "source":"admin_confirmed",
                    }),
                ),
            )
    return {
        "id":row["id"],
        "email":row["email"],
        "linked_registered_user":bool(row["user_id"]),
        "consent_at":str(row["consent_at"]),
    }


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
    where=[
        "ms.consent_at is not null",
        "ms.unsubscribed_at is null",
        "u.id is not null",
    ]
    if account_type:
        where.append("p.account_type=%s")
        params.append(account_type)
    rows=conn.execute(
        f"""select u.id user_id,lower(ms.email) email,coalesce(p.name,'') name
            from private.marketing_subscribers ms
            join auth.users u on lower(u.email)=lower(ms.email)
            left join public.profiles p on p.id=u.id
            where {' and '.join(where)}
            order by ms.created_at asc
            limit 5000""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def _external_recipients(conn):
    rows=conn.execute(
        """select null::uuid user_id,lower(ms.email) email,''::text name
           from private.marketing_subscribers ms
           left join auth.users u on lower(u.email)=lower(ms.email)
           where ms.consent_at is not null
             and ms.unsubscribed_at is null
             and u.id is null
           order by ms.created_at asc
           limit 5000"""
    ).fetchall()
    return [dict(row) for row in rows]


def _all_recipients(conn):
    rows=conn.execute(
        """select u.id user_id,lower(ms.email) email,coalesce(p.name,'') name
           from private.marketing_subscribers ms
           left join auth.users u on lower(u.email)=lower(ms.email)
           left join public.profiles p on p.id=u.id
           where ms.consent_at is not null
             and ms.unsubscribed_at is null
           order by ms.created_at asc
           limit 5000"""
    ).fetchall()
    return [dict(row) for row in rows]


def _custom_recipients(conn,requested):
    unique=[]
    seen=set()
    for email in requested or []:
        normalized=str(email).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    if not unique:
        return []

    rows=conn.execute(
        """select u.id user_id,lower(ms.email) email,coalesce(p.name,'') name
           from private.marketing_subscribers ms
           left join auth.users u on lower(u.email)=lower(ms.email)
           left join public.profiles p on p.id=u.id
           where lower(ms.email)=any(%s::text[])
             and ms.consent_at is not null
             and ms.unsubscribed_at is null""",
        (unique,),
    ).fetchall()
    recipients=[dict(row) for row in rows]
    matched={row["email"] for row in recipients}
    missing=[email for email in unique if email not in matched]
    if missing:
        raise RoyaError(
            "MARKETING_CONSENT_REQUIRED",
            f"{len(missing)} selected recipient(s) do not have active marketing consent.",
            422,
            {"missing_count":len(missing)},
        )
    return recipients


def queue_campaign(
    *,
    audience,
    subject,
    body,
    actor_user_id,
    custom_recipients=None,
    template_id=None,
):
    allowed={
        "all","registered","external",
        "registered_all","registered_guests","registered_hotels","custom",
    }
    if audience not in allowed:
        raise RoyaError("VALIDATION_ERROR","Choose a valid email audience.",422)

    campaign_id=str(uuid4())
    request_key=str(uuid4())
    queued_ids=[]

    with db_connection() as conn:
        with conn.transaction():
            if audience=="custom":
                recipients=_custom_recipients(conn,custom_recipients)
            elif audience=="external":
                recipients=_external_recipients(conn)
            elif audience=="all":
                recipients=_all_recipients(conn)
            else:
                recipients=_registered_recipients(conn,audience)

            if not recipients:
                raise RoyaError(
                    "NO_EMAIL_RECIPIENTS",
                    "No consented recipients matched this audience.",
                    422,
                )

            if len(recipients)>5000:
                raise RoyaError(
                    "EMAIL_AUDIENCE_TOO_LARGE",
                    "This campaign exceeds the current 5,000-recipient safety limit.",
                    422,
                )

            conn.execute(
                """insert into private.marketing_campaigns(
                     id,template_id,audience,subject,body,request_key,
                     requested_recipients,created_by
                   ) values(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    campaign_id,
                    str(template_id) if template_id else None,
                    audience,
                    subject,
                    body,
                    request_key,
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
                       on conflict do nothing
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
                if row:
                    queued_ids.append(str(row["id"]))

            conn.execute(
                """update private.marketing_campaigns
                   set queued_recipients=%s
                   where id=%s""",
                (len(queued_ids),campaign_id),
            )
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,'email_campaign.queued','marketing_campaign',%s,%s::jsonb)""",
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

    immediate_ids=queued_ids[:10]
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


def deliver_email_queue(limit=50):
    return NotificationService().deliver_pending_emails(
        limit=max(1,min(int(limit),100))
    )
