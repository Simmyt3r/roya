from io import BytesIO
from werkzeug.datastructures import FileStorage

from roya.common.media import MAX_IMAGE_BYTES, read_image_upload, storage_object_path


def test_storage_object_path_extracts_property_image_key():
    url="https://project.supabase.co/storage/v1/object/public/property-images/abc/room%201.webp"
    assert storage_object_path(url,"property-images")=="abc/room 1.webp"


def test_storage_object_path_rejects_wrong_bucket():
    url="https://project.supabase.co/storage/v1/object/public/room-images/a/b.webp"
    assert storage_object_path(url,"property-images") is None


def test_photo_limit_fits_vercel_function_request_body():
    assert MAX_IMAGE_BYTES == 4 * 1024 * 1024
    upload = FileStorage(stream=BytesIO(b"x" * (MAX_IMAGE_BYTES + 1)), filename="room.png", content_type="image/png")
    try:
        read_image_upload(upload)
    except ValueError as exc:
        assert str(exc) == "IMAGE_TOO_LARGE"
    else:
        raise AssertionError("Oversized photo must be rejected")
