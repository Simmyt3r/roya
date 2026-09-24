from urllib.parse import unquote,urlparse

MAX_IMAGE_BYTES=10*1024*1024
ALLOWED_IMAGE_TYPES={
    "image/jpeg":".jpg",
    "image/png":".png",
    "image/webp":".webp",
}


def read_image_upload(file):
    if not file or not getattr(file,"filename",None):
        raise ValueError("IMAGE_REQUIRED")
    mimetype=getattr(file,"mimetype",None)
    if mimetype not in ALLOWED_IMAGE_TYPES:
        raise ValueError("IMAGE_TYPE")
    raw=file.read(MAX_IMAGE_BYTES+1)
    if len(raw)>MAX_IMAGE_BYTES:
        raise ValueError("IMAGE_TOO_LARGE")
    return raw,ALLOWED_IMAGE_TYPES[mimetype]


def storage_object_path(public_url,bucket):
    if not public_url:
        return None
    marker=f"/storage/v1/object/public/{bucket}/"
    path=urlparse(str(public_url)).path
    if marker not in path:
        return None
    object_path=path.split(marker,1)[1]
    return unquote(object_path) or None
