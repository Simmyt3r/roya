from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest

from roya import create_app
from roya.auth import service as auth_service
from roya.properties import routes as properties
from roya.rooms import routes as rooms


class Database:
    def __init__(self):
        self.statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, *_):
        self.statement = statement
        if "insert into property_images" in statement or "insert into room_images" in statement:
            raise RuntimeError("database write failed")
        return self

    def fetchone(self):
        return {"organization_id": str(uuid4())}


class Storage:
    def __init__(self):
        self.uploaded = []
        self.removed = []

    def upload(self, path, raw, options):
        self.uploaded.append(path)

    def get_public_url(self, path):
        return f"https://example.supabase.co/storage/v1/object/public/images/{path}"

    def remove(self, paths):
        self.removed.extend(paths)


@pytest.mark.parametrize("kind", ["property", "room"])
def test_upload_validates_alt_text_before_storage(monkeypatch, kind):
    storage = Storage()
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda _: storage))
    user = SimpleNamespace(user_id=str(uuid4()))
    monkeypatch.setattr(auth_service, "current_identity", lambda required=False: user)
    module = properties if kind == "property" else rooms
    monkeypatch.setattr(module, "current_identity", lambda required=False: user)
    monkeypatch.setattr(module, "db_connection", lambda: Database())
    monkeypatch.setattr(module, "supabase_admin_client", lambda: client)
    monkeypatch.setattr(properties, "require_organization_member", lambda *args: None)
    monkeypatch.setattr(rooms, "_room_media_access", lambda *args: {"role": "owner"})

    endpoint = (
        f"/api/v1/properties/{uuid4()}/images" if kind == "property"
        else f"/api/v1/room-types/{uuid4()}/images"
    )
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    response = app.test_client().post(endpoint, data={
        "file": (BytesIO(b"image"), "photo.png", "image/png"),
        "alt_text": "x" * 301,
    })

    assert response.status_code == 422
    assert not storage.uploaded


@pytest.mark.parametrize("kind", ["property", "room"])
def test_failed_image_database_write_removes_uploaded_object(monkeypatch, kind):
    storage = Storage()
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda _: storage))
    user = SimpleNamespace(user_id=str(uuid4()))
    monkeypatch.setattr(auth_service, "current_identity", lambda required=False: user)
    module = properties if kind == "property" else rooms
    monkeypatch.setattr(module, "current_identity", lambda required=False: user)
    monkeypatch.setattr(module, "db_connection", lambda: Database())
    monkeypatch.setattr(module, "supabase_admin_client", lambda: client)
    monkeypatch.setattr(properties, "require_organization_member", lambda *args: None)
    monkeypatch.setattr(rooms, "_room_media_access", lambda *args: {"role": "owner"})

    endpoint = (
        f"/api/v1/properties/{uuid4()}/images" if kind == "property"
        else f"/api/v1/room-types/{uuid4()}/images"
    )
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with pytest.raises(RuntimeError, match="database write failed"):
        app.test_client().post(endpoint, data={
            "file": (BytesIO(b"image"), "photo.png", "image/png"),
            "alt_text": "A welcoming room",
        })

    assert len(storage.uploaded) == 1
    assert storage.removed == storage.uploaded
