from dataclasses import dataclass
from flask import jsonify, request


@dataclass
class RoyaError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict | None = None


def json_error(error: RoyaError):
    return (
        jsonify(
            {
                "success": False,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details or {},
                },
                "meta": {"request_id": getattr(request, "request_id", None)},
            }
        ),
        error.status_code,
    )


def register_error_handlers(app):
    @app.errorhandler(RoyaError)
    def handle_roya_error(error):
        return json_error(error)

    @app.errorhandler(404)
    def handle_404(_error):
        if request.path.startswith("/api/"):
            return json_error(RoyaError("NOT_FOUND", "Resource not found.", 404))
        return "Not found", 404

    @app.errorhandler(500)
    def handle_500(_error):
        if request.path.startswith("/api/"):
            return json_error(RoyaError("INTERNAL_ERROR", "An unexpected error occurred.", 500))
        return _error
