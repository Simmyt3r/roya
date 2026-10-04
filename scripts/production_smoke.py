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


def run(base_url=None):
    base=(base_url or os.getenv("IROYA_URL") or "https://iroya.vercel.app").rstrip("/")
    request=Request(base+"/health",headers={"User-Agent":"iroya-release-smoke/1.0"})
    try:
        with urlopen(request,timeout=20) as response:
            payload=json.loads(response.read().decode("utf-8"))
    except (HTTPError,URLError,TimeoutError,ValueError) as exc:
        return {"passed":False,"error":str(exc),"url":base+"/health"}

    data=payload.get("data") or {}
    checks=data.get("checks") or {}
    passed=bool(
        payload.get("success")
        and data.get("database_reachable")
        and checks.get("booking_schema_ready")
        and checks.get("inventory_consistent")
        and checks.get("operations_scan_active")
        and data.get("integrations",{}).get("payments_configured")
    )
    return {
        "passed":passed,
        "url":base+"/health",
        "status":data.get("status"),
        "booking_ready":data.get("booking_ready"),
        "database_reachable":data.get("database_reachable"),
        "checks":checks,
        "integrations":data.get("integrations") or {},
        "blockers":data.get("blockers") or [],
    }


if __name__=="__main__":
    result=run()
    print(json.dumps(result,indent=2,default=str))
    sys.exit(0 if result["passed"] else 1)
