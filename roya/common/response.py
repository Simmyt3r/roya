from flask import jsonify, request


def ok(data=None, status=200, **meta):
    payload = {
        "success": True,
        "data": data if data is not None else {},
        "meta": {"request_id": getattr(request, "request_id", None), **meta},
    }
    return jsonify(payload), status
