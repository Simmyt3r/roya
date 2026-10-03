from flask import Blueprint,request
from pydantic import ValidationError

from roya.auth.service import current_identity,login_required
from roya.common.errors import RoyaError
from roya.common.response import ok
from .schemas import ReviewCreate
from .service import ReviewService


bp=Blueprint("reviews",__name__)
service=ReviewService()


@bp.post("/api/v1/reviews")
@login_required
def create_review():
    try:
        payload=ReviewCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        raise RoyaError(
            "VALIDATION_ERROR",
            "Invalid review details.",
            422,
            {"errors":exc.errors()},
        ) from exc
    identity=current_identity(required=True)
    return ok(service.create(identity.user_id,payload),201)


@bp.get("/api/v1/properties/<uuid:property_id>/reviews")
def public_reviews(property_id):
    try:
        limit=int(request.args.get("limit","20"))
    except ValueError as exc:
        raise RoyaError("VALIDATION_ERROR","Review limit must be a whole number.",422) from exc
    return ok({
        "summary":service.summary(str(property_id)),
        "reviews":service.list_public(str(property_id),limit=limit),
    })
