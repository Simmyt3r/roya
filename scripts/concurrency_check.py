import concurrent.futures,os,uuid
from datetime import date,timedelta
import psycopg

def _book(index):
    conn=psycopg.connect(os.environ["TEST_DATABASE_URL"],prepare_threshold=None)
    try:
        with conn.transaction():
            return conn.execute(
                """select * from create_reservation(%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s,%s,1,1,0,%s,%s,%s,'pay_at_property',%s)""",
                (os.environ["ROYA_TEST_USER_ID"],os.environ["ROYA_TEST_PROPERTY_ID"],os.environ["ROYA_TEST_ROOM_TYPE_ID"],os.environ["ROYA_TEST_RATE_PLAN_ID"],os.environ.get("ROYA_TEST_CHECK_IN",(date.today()+timedelta(days=30)).isoformat()),os.environ.get("ROYA_TEST_CHECK_OUT",(date.today()+timedelta(days=31)).isoformat()),f"Race Guest {index}",f"race{index}@example.com","+2348000000000",f"race-{uuid.uuid4()}"),
            ).fetchone()
    finally: conn.close()

def run_concurrency_check():
    successes=conflicts=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(_book,i) for i in range(2)]:
            try: future.result(); successes+=1
            except Exception as exc:
                if "BOOKING_CONFLICT" in str(exc): conflicts+=1
                else: raise
    return {"successes":successes,"conflicts":conflicts}

if __name__=="__main__": print(run_concurrency_check())
