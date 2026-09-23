import logging
import uuid
from flask import Flask, request
from flask_wtf.csrf import CSRFProtect

from .config import Config
from .common.errors import register_error_handlers
from .common.logging import JsonFormatter

csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    csrf.init_app(app)
    register_error_handlers(app)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def attach_request_id():
        request.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = getattr(request, "request_id", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        return response

    from .properties.routes import bp as properties_bp
    from .auth.routes import bp as auth_bp
    from .reservations.routes import bp as reservations_bp
    from .payments.routes import bp as payments_bp
    from .admin.routes import bp as admin_bp
    from .inventory.routes import bp as inventory_bp
    from .organizations.routes import bp as organizations_bp
    from .rooms.routes import bp as rooms_bp
    from .rates.routes import bp as rates_bp

    app.register_blueprint(properties_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(organizations_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(rates_bp)

    for api_blueprint in (auth_bp, reservations_bp, payments_bp, admin_bp, inventory_bp, organizations_bp, rooms_bp, rates_bp, properties_bp):
        csrf.exempt(api_blueprint)

    return app
