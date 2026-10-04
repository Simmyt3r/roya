from urllib.parse import urlsplit

from flask import current_app

from roya.common.errors import RoyaError
from roya.common.slug import slugify


RESERVED_HOTEL_SUBDOMAINS={
    "www","app","admin","api","static","cdn","mail","smtp","support",
    "help","status","blog","auth","login","register","dashboard","partner",
    "hotels","search","book","booking","payments","pay","media","assets",
}


def hotel_domain_base():
    return (current_app.config.get("HOTEL_DOMAIN_BASE") or "iroya.ng").strip().lower().strip(".")


def mini_domain_url(value):
    if not value:
        return None
    return f"https://{value}.{hotel_domain_base()}"


def normalize_mini_domain(value):
    candidate=slugify((value or "").strip())[:63].strip("-")
    if len(candidate)<2:
        raise RoyaError("VALIDATION_ERROR","Mini-domain must contain at least 2 letters or numbers.",422)
    if candidate in RESERVED_HOTEL_SUBDOMAINS:
        raise RoyaError("MINI_DOMAIN_RESERVED","That iRoya mini-domain is reserved.",409)
    return candidate


def allocate_mini_domain(conn,name):
    base=normalize_mini_domain(name)
    candidate=base
    suffix=2
    while conn.execute(
        "select 1 from properties where lower(mini_domain)=lower(%s) limit 1",
        (candidate,),
    ).fetchone():
        tail=f"-{suffix}"
        candidate=f"{base[:63-len(tail)].rstrip('-')}{tail}"
        suffix+=1
        if suffix>9999:
            raise RoyaError("MINI_DOMAIN_UNAVAILABLE","A mini-domain could not be allocated.",409)
    return candidate


def property_subdomain_from_host(host):
    host=(host or "").split(":",1)[0].lower().strip(".")
    base=hotel_domain_base()
    if host in {base,f"www.{base}"}:
        return None
    suffix=f".{base}"
    if not host.endswith(suffix):
        return None
    label=host[:-len(suffix)]
    if not label or "." in label or label in RESERVED_HOTEL_SUBDOMAINS:
        return None
    return label
