"""Server-only integration settings. Credentials are decrypted from Vault on demand."""

import json

from flask import current_app

from .db import db_connection
from .errors import RoyaError


PROVIDERS = {"smtp", "paystack"}


def _stored(provider):
    if provider not in PROVIDERS:
        raise ValueError("Unknown integration")
    if not current_app.config.get("DATABASE_URL"):
        return None
    with db_connection() as conn:
        return conn.execute(
            """select s.configuration,s.secret_id,v.decrypted_secret
               from private.integration_settings s
               left join vault.decrypted_secrets v on v.id=s.secret_id
               where s.provider=%s""",
            (provider,),
        ).fetchone()


def paystack_settings():
    row=_stored("paystack")
    if row:
        config=row["configuration"] or {}
        return {
            "source":"dashboard",
            "public_key":config.get("public_key", ""),
            "mode":config.get("mode", ""),
            "secret_key":row["decrypted_secret"] or "",
        }
    secret=current_app.config.get("PAYSTACK_SECRET_KEY", "")
    return {
        "source":"environment" if secret else "none",
        "public_key":current_app.config.get("PAYSTACK_PUBLIC_KEY", ""),
        "mode":"live" if secret.startswith("sk_live_") else "test" if secret.startswith("sk_test_") else "",
        "secret_key":secret,
    }


def smtp_settings():
    row=_stored("smtp")
    if row:
        config=row["configuration"] or {}
        return {
            "source":"dashboard",
            "host":config.get("host", ""),
            "port":config.get("port", 587),
            "security":config.get("security", "starttls"),
            "username":config.get("username", ""),
            "password":row["decrypted_secret"] or "",
            "sender":config.get("sender", ""),
        }
    host=current_app.config.get("SMTP_HOST", "")
    security=current_app.config.get("SMTP_SECURITY") or (
        "starttls" if current_app.config.get("SMTP_TLS", True) else "none"
    )
    return {
        "source":"environment" if host else "none",
        "host":host,
        "port":current_app.config.get("SMTP_PORT", 587),
        "security":security,
        "username":current_app.config.get("SMTP_USERNAME", ""),
        "password":current_app.config.get("SMTP_PASSWORD", ""),
        "sender":current_app.config.get("SMTP_FROM", ""),
    }


def integration_status(provider):
    if provider=="paystack":
        settings=paystack_settings()
        return {
            "configured":bool(settings["secret_key"]),
            "source":settings["source"],
            "mode":settings["mode"],
            "public_key":settings["public_key"],
            "has_secret":bool(settings["secret_key"]),
        }
    if provider=="smtp":
        settings=smtp_settings()
        return {
            "configured":bool(settings["host"] and settings["sender"] and
                              (not settings["username"] or settings["password"])),
            "source":settings["source"],
            "host":settings["host"],
            "port":settings["port"],
            "security":settings["security"],
            "username":settings["username"],
            "sender":settings["sender"],
            "has_password":bool(settings["password"]),
        }
    raise ValueError("Unknown integration")


def save_integration(provider,configuration,secret,actor_user_id):
    if provider not in PROVIDERS:
        raise ValueError("Unknown integration")
    with db_connection() as conn:
        with conn.transaction():
            conn.execute(
                """insert into private.integration_settings(provider)
                   values(%s) on conflict(provider) do nothing""",
                (provider,),
            )
            row=conn.execute(
                """select secret_id from private.integration_settings
                   where provider=%s for update""",
                (provider,),
            ).fetchone()
            secret_id=row["secret_id"]
            if secret:
                if secret_id:
                    conn.execute(
                        "select vault.update_secret(%s::uuid,%s)",
                        (str(secret_id),secret),
                    )
                else:
                    secret_id=conn.execute(
                        "select vault.create_secret(%s,%s,%s) secret_id",
                        (secret,f"iroya.{provider}.credential",f"iRoya {provider} credential"),
                    ).fetchone()["secret_id"]
            elif not secret_id:
                raise RoyaError(
                    "CREDENTIAL_REQUIRED",
                    "Enter the credential when first saving this integration.",
                    422,
                )

            conn.execute(
                """update private.integration_settings
                   set configuration=%s::jsonb,secret_id=%s::uuid,
                       updated_by=%s::uuid,updated_at=now()
                   where provider=%s""",
                (json.dumps(configuration),str(secret_id),actor_user_id,provider),
            )
            conn.execute(
                """insert into audit_logs(actor_user_id,action,entity_type,entity_id,after_json)
                   values(%s,%s,'integration',%s,%s::jsonb)""",
                (actor_user_id,f"integration.{provider}_configured",provider,
                 json.dumps({"provider":provider,"credential_rotated":bool(secret)})),
            )
