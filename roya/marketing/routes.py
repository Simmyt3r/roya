from flask import Blueprint, render_template, request

from roya.common.errors import RoyaError
from .service import preview_unsubscribe, unsubscribe_by_token


bp = Blueprint("marketing", __name__)


@bp.route("/email/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    try:
        preview = preview_unsubscribe(token)
    except RoyaError:
        return render_template(
            "marketing/unsubscribe.html",
            invalid=True,
            completed=False,
            masked_email=None,
        ), 400

    if request.method == "POST":
        try:
            result = unsubscribe_by_token(token)
        except RoyaError:
            return render_template(
                "marketing/unsubscribe.html",
                invalid=True,
                completed=False,
                masked_email=None,
            ), 400
        return render_template(
            "marketing/unsubscribe.html",
            invalid=False,
            completed=True,
            masked_email=result["masked_email"],
        )

    return render_template(
        "marketing/unsubscribe.html",
        invalid=False,
        completed=False,
        masked_email=preview["masked_email"],
    )
