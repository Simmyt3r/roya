from roya.common.media import storage_object_path


def test_storage_object_path_extracts_property_image_key():
    url="https://project.supabase.co/storage/v1/object/public/property-images/abc/room%201.webp"
    assert storage_object_path(url,"property-images")=="abc/room 1.webp"


def test_storage_object_path_rejects_wrong_bucket():
    url="https://project.supabase.co/storage/v1/object/public/room-images/a/b.webp"
    assert storage_object_path(url,"property-images") is None
