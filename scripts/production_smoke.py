"""Small production smoke check for iRoya's public readiness endpoint.

Usage:
    python scripts/production_smoke.py
    IROYA_URL=https://iroya.vercel.app python scripts/production_smoke.py
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def run(base_url=None,scope=None):
    base=(base_url or os.getenv("IROYA_URL") or "https://iroya.vercel.app").rstrip("/")
    readiness_scope=(scope or os.getenv("IROYA_READINESS_SCOPE") or "core").strip().lower()
    if readiness_scope not in {"core","release"}:
        raise ValueError("IROYA_READINESS_SCOPE must be core or release.")
    request=Request(base+"/health",headers={"User-Agent":"iroya-release-smoke/1.0"})
    try:
        with urlopen(request,timeout=20) as response:
            payload=json.loads(response.read().decode("utf-8"))
    except (HTTPError,URLError,TimeoutError,ValueError) as exc:
        return {"passed":False,"error":str(exc),"url":base+"/health"}

    data=payload.get("data") or {}
    checks=data.get("checks") or {}
    readiness_key="release_ready" if readiness_scope=="release" else "core_ready"
    passed=bool(
        payload.get("success")
        and data.get(readiness_key)
        and data.get("database_reachable")
        and checks.get("booking_schema_ready")
        and checks.get("inventory_consistent")
        and checks.get("operations_scan_active")
    )
    return {
        "passed":passed,
        "url":base+"/health",
        "status":data.get("status"),
        "scope":readiness_scope,
        "core_ready":data.get("core_ready"),
        "release_ready":data.get("release_ready"),
        "booking_ready":data.get("booking_ready"),
        "database_reachable":data.get("database_reachable"),
        "checks":checks,
        "integrations":data.get("integrations") or {},
        "core_blockers":data.get("core_blockers") or [],
        "release_blockers":data.get("release_blockers") or data.get("blockers") or [],
        "deferred":data.get("deferred") or [],
        "blockers":data.get("blockers") or [],
    }


if __name__=="__main__":
    result=run()
    print(json.dumps(result,indent=2,default=str))
    sys.exit(0 if result["passed"] else 1)
