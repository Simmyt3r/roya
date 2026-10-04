import concurrent.futures
import os
import uuid
from datetime import date,timedelta

import psycopg


def _ids():
    return {
        "user":uuid.uuid4(),
        "organization":uuid.uuid4(),
        "property":uuid.uuid4(),
        "room":uuid.uuid4(),
        "rate":uuid.uuid4(),
    }


def _setup_fixture(database_url):
    ids=_ids()
    check_in=date.today()+timedelta(days=35)
    check_out=check_in+timedelta(days=1)
    with psycopg.connect(database_url,autocommit=True,prepare_threshold=None) as conn:
        conn.execute(
            "insert into auth.users(id,is_sso_user,is_anonymous) values(%s,false,false)",
            (ids["user"],),
        )
        conn.execute(
            """insert into public.organizations(id,name,slug,status)
               values(%s,'Concurrency Certification',%s,'active')""",
            (ids["organization"],f"concurrency-cert-{str(ids['organization'])[:8]}"),
        )
        conn.execute(
            """insert into public.organization_members(organization_id,user_id,role,status)
               values(%s,%s,'owner','active')""",
            (ids["organization"],ids["user"]),
        )
        conn.execute(
            """insert into public.properties(
                 id,organization_id,created_by_user_id,name,slug,address,city,state,
                 verification_status,status
               ) values(%s,%s,%s,'Concurrency Certification Hotel',%s,
                        '1 Test Lane','Lagos','Lagos','verified','active')""",
            (
                ids["property"],ids["organization"],ids["user"],
                f"concurrency-cert-hotel-{str(ids['property'])[:8]}",
            ),
        )
        conn.execute(
            """insert into public.room_types(
                 id,property_id,name,capacity_adults,capacity_children,total_inventory,status
               ) values(%s,%s,'Last Room',2,0,1,'active')""",
            (ids["room"],ids["property"]),
        )
        conn.execute(
            """insert into public.rate_plans(
                 id,room_type_id,name,base_price_minor,guarantee_type,deposit_percent,status
               ) values(%s,%s,'Race rate',5000000,'pay_at_property',100,'active')""",
            (ids["rate"],ids["room"]),
        )
        conn.execute(
            """insert into public.inventory_days(room_type_id,date,total_inventory)
               values(%s,%s,1)""",
            (ids["room"],check_in),
        )
    return {**ids,"check_in":check_in,"check_out":check_out}


def _book(database_url,fixture,index,barrier):
    with psycopg.connect(database_url,prepare_threshold=None) as conn:
        barrier.wait(timeout=10)
        with conn.transaction():
            return conn.execute(
                """select * from public.create_reservation(
                     %s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,1,1,0,
                     %s,%s,%s,'pay_at_property',%s
                   )""",
                (
                    fixture["user"],fixture["property"],fixture["room"],fixture["rate"],
                    fixture["check_in"],fixture["check_out"],
                    f"Race Guest {index}",f"race-{fixture['user']}-{index}@example.com",
                    "+2348000000000",f"race-{uuid.uuid4()}",
                ),
            ).fetchone()


def _cleanup_fixture(database_url,fixture):
    with psycopg.connect(database_url,autocommit=True,prepare_threshold=None) as conn:
        rows=conn.execute(
            "select id from public.reservations where property_id=%s",
            (fixture["property"],),
        ).fetchall()
        reservation_ids=[row[0] for row in rows]
        if reservation_ids:
            conn.execute(
                "delete from public.notifications where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                "delete from public.refunds where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                "delete from public.payment_transactions where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                "delete from public.payments where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                "delete from public.reservation_nights where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                "delete from public.reservation_items where reservation_id=any(%s::uuid[])",
                (reservation_ids,),
            )
            conn.execute(
                """delete from public.audit_logs
                   where organization_id=%s or property_id=%s
                      or (entity_type='reservation' and entity_id=any(%s::text[]))""",
                (
                    fixture["organization"],fixture["property"],
                    [str(value) for value in reservation_ids],
                ),
            )
            conn.execute(
                "delete from public.reservations where id=any(%s::uuid[])",
                (reservation_ids,),
            )
        conn.execute(
            "delete from public.idempotency_keys where user_id=%s",
            (fixture["user"],),
        )
        conn.execute(
            "delete from public.inventory_days where room_type_id=%s",
            (fixture["room"],),
        )
        conn.execute("delete from public.rate_plans where id=%s",(fixture["rate"],))
        conn.execute("delete from public.room_types where id=%s",(fixture["room"],))
        conn.execute("delete from public.properties where id=%s",(fixture["property"],))
        conn.execute(
            "delete from public.organization_members where organization_id=%s",
            (fixture["organization"],),
        )
        conn.execute(
            "delete from public.organizations where id=%s",
            (fixture["organization"],),
        )
        conn.execute("delete from public.profiles where id=%s",(fixture["user"],))
        conn.execute("delete from auth.users where id=%s",(fixture["user"],))


def run_concurrency_check(database_url=None):
    url=database_url or os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is required. Use a disposable Supabase/Postgres database, never production."
        )

    fixture=_setup_fixture(url)
    successes=0
    conflicts=0
    unexpected=[]
    barrier=__import__("threading").Barrier(2)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(_book,url,fixture,index,barrier) for index in range(2)]
            for future in futures:
                try:
                    future.result()
                    successes+=1
                except Exception as exc:
                    if "BOOKING_CONFLICT" in str(exc):
                        conflicts+=1
                    else:
                        unexpected.append(str(exc))
        if unexpected:
            raise RuntimeError("Unexpected concurrency failure: "+" | ".join(unexpected))
        return {
            "successes":successes,
            "conflicts":conflicts,
            "passed":successes==1 and conflicts==1,
            "fixture_cleaned":True,
        }
    finally:
        _cleanup_fixture(url,fixture)


if __name__=="__main__":
    result=run_concurrency_check()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
