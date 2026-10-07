from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from roya import create_app
from roya.auth import service as auth_service
from roya.common.errors import RoyaError
from roya.rooms import routes as room_routes


class _Txn:
    def __enter__(self):
        return self

    def __exit__(self,*_args):
        return False


class _Result:
    def __init__(self,row=None,rows=None):
        self.row=row
        self.rows=rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _RoomReadinessConnection:
    def __init__(self,occupied=False):
        self.occupied=occupied
        self.created=[]
        self.deleted=False
        self.updated_status=None

    def transaction(self):
        return _Txn()

    def execute(self,sql,params=None):
        if "select rt.id room_type_id" in sql:
            return _Result(row={
                "room_type_id":"room-type-1",
                "property_id":"property-1",
                "total_inventory":3,
                "organization_id":"org-1",
                "role":"owner",
            })
        if "select room_number from physical_rooms" in sql:
            return _Result(rows=[])
        if "select count(*) total from physical_rooms" in sql:
            return _Result(row={"total":0})
        if "insert into physical_rooms(" in sql:
            number=params[1]
            row={
                "id":f"physical-{number}",
                "room_type_id":"room-type-1",
                "room_number":number,
                "floor":params[2],
                "status":"active",
                "housekeeping_status":"ready",
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-07",
            }
            self.created.append(row)
            return _Result(row=row)
        if "select pr.*,rt.property_id" in sql:
            return _Result(row={
                "id":"physical-101",
                "room_type_id":"room-type-1",
                "room_number":"101",
                "floor":"1",
                "status":"active",
                "housekeeping_status":"ready",
                "current_reservation_id":"reservation-1" if self.occupied else None,
                "property_id":"property-1",
                "organization_id":"org-1",
                "role":"owner",
            })
        if "update physical_rooms" in sql and "housekeeping_status=%s" in sql:
            self.updated_status=params[0]
            return _Result(row={
                "id":"physical-101",
                "room_type_id":"room-type-1",
                "room_number":"101",
                "floor":"1",
                "status":"active",
                "housekeeping_status":params[0],
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-07",
            })
        if "set status='out_of_service'" in sql:
            self.updated_status="out_of_service"
            return _Result(row={
                "id":"physical-101",
                "room_type_id":"room-type-1",
                "room_number":"101",
                "floor":"1",
                "status":"out_of_service",
                "housekeeping_status":"ready",
                "current_reservation_id":None,
                "housekeeping_updated_at":"2026-10-07",
            })
        if "delete from physical_rooms" in sql:
            self.deleted=True
            return _Result()
        if "insert into audit_logs" in sql:
            return _Result()
        raise AssertionError(sql)


def _client(monkeypatch,connection):
    identity=SimpleNamespace(user_id=str(uuid4()),email="rooms@example.com")
    monkeypatch.setattr(auth_service,"current_identity",lambda required=False:identity)
    monkeypatch.setattr(room_routes,"current_identity",lambda required=False:identity)

    @contextmanager
    def _connection():
        yield connection

    monkeypatch.setattr(room_routes,"db_connection",lambda:_connection())
    app=create_app({"TESTING":True,"WTF_CSRF_ENABLED":False,"DATABASE_URL":""})
    return app.test_client()


def test_batch_room_numbers_default_to_ready(monkeypatch):
    connection=_RoomReadinessConnection()
    client=_client(monkeypatch,connection)
    room_type_id=uuid4()

    response=client.post(
        f"/api/v1/room-types/{room_type_id}/physical-rooms",
        json={"room_numbers":["101","102"],"floor":"1"},
    )

    assert response.status_code==201
    data=response.get_json()["data"]
    assert [row["room_number"] for row in data]==["101","102"]
    assert all(row["housekeeping_status"]=="ready" for row in data)


def test_room_readiness_can_move_to_cleaning(monkeypatch):
    connection=_RoomReadinessConnection()
    client=_client(monkeypatch,connection)
    room_id=uuid4()

    response=client.put(
        f"/api/v1/physical-rooms/{room_id}/readiness",
        json={"status":"cleaning"},
    )

    assert response.status_code==200
    assert response.get_json()["data"]["readiness_status"]=="cleaning"
    assert connection.updated_status=="cleaning"


def test_occupied_room_cannot_change_readiness(monkeypatch):
    connection=_RoomReadinessConnection(occupied=True)
    client=_client(monkeypatch,connection)
    room_id=uuid4()

    response=client.put(
        f"/api/v1/physical-rooms/{room_id}/readiness",
        json={"status":"dirty"},
    )

    assert response.status_code==409
    assert response.get_json()["error"]["code"]=="ROOM_OCCUPIED"


def test_occupied_room_cannot_be_removed(monkeypatch):
    connection=_RoomReadinessConnection(occupied=True)
    client=_client(monkeypatch,connection)
    room_id=uuid4()

    response=client.delete(f"/api/v1/physical-rooms/{room_id}")

    assert response.status_code==409
    assert response.get_json()["error"]["code"]=="ROOM_OCCUPIED"
    assert connection.deleted is False
