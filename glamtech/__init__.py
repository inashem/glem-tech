import os
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from werkzeug.exceptions import SecurityError

from .models import User, db

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])


@event.listens_for(Engine, "connect")
def sqlite_foreign_keys(connection, record):
    if type(connection).__module__.startswith("sqlite3"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    environment = os.getenv("APP_ENV", "development")
    if environment not in {"development", "production"}:
        raise RuntimeError("APP_ENV must be development or production.")
    production = environment == "production"
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///dev.sqlite3"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        STORAGE_ROOT=os.getenv("STORAGE_ROOT", str(Path(app.instance_path) / "dev-storage")),
        STORAGE_BACKEND=os.getenv("STORAGE_BACKEND", "local-development"),
        MAX_CONTENT_LENGTH=17 * 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=20,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        TRUSTED_HOSTS=os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(","),
        PRODUCTION=production,
    )
    if test_config:
        app.config.update(test_config)
    secret = app.config["SECRET_KEY"]
    if not secret or len(secret) < 32 or secret.startswith("REPLACE_"):
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters.")
    if production:
        if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"):
            raise RuntimeError("Production requires PostgreSQL via psycopg.")
        database_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        if database_url.query.get("sslmode") != "verify-full" or not database_url.query.get("sslrootcert"):
            raise RuntimeError("Production PostgreSQL requires verify-full TLS and sslrootcert.")
        if not os.getenv("STORAGE_ROOT") or app.config["STORAGE_BACKEND"] not in {"smb", "local-restricted"}:
            raise RuntimeError("Production requires an explicit restricted storage path and backend.")
        if app.config["RATELIMIT_STORAGE_URI"].startswith("memory:"):
            raise RuntimeError("Production requires shared rate-limit storage (Redis).")
        if not os.getenv("TRUSTED_HOSTS"):
            raise RuntimeError("Production requires TRUSTED_HOSTS.")
        # Only Nginx can reach localhost Gunicorn; trust one proxy for client IP and HTTPS.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    Path(app.instance_path).mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path(app.config["STORAGE_ROOT"]).resolve()
    public_root = Path(app.static_folder).resolve()
    if root == public_root or public_root in root.parents or root in public_root.parents:
        raise RuntimeError("Storage must be separate from the public static directory.")
    if app.config["STORAGE_BACKEND"] == "smb" and not os.path.ismount(root):
        raise RuntimeError("SMB storage must be mounted; refusing to silently fall back to a local folder.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("photos", "private"):
        directory = root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
    app.config["STORAGE_ROOT"] = str(root)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    from .routes import bp
    app.register_blueprint(bp)

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    for code in (400, 403, 404, 409, 413, 429, 500, 503):
        def error_page(error, code=code):
            if isinstance(error, SecurityError):
                return "Bad request: untrusted host.", 400, {"Content-Type": "text/plain; charset=utf-8"}
            return render_template("error.html", code=code), code
        app.register_error_handler(code, error_page)

    @app.cli.command("init-db")
    def init_db():
        """Create the initial schema; not a migration mechanism."""
        db.create_all()
        click.echo("Initial database schema created.")

    @app.cli.command("create-staff")
    @click.option("--email", required=True)
    def create_staff(email):
        """Provision staff locally. Password comes from STAFF_PASSWORD, never an argument."""
        import re
        password = os.getenv("STAFF_PASSWORD", "")
        email = email.strip().lower()
        if len(password) < 12 or len(password) > 128 or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise click.ClickException("Set STAFF_PASSWORD (12–128 characters) and supply a valid email.")
        if db.session.scalar(db.select(User).where(User.email == email)):
            raise click.ClickException("Email already exists; accounts are never promoted automatically.")
        db.session.add(User(email=email, password_hash=generate_password_hash(password), role="staff"))
        db.session.commit()
        click.echo(f"Staff account created: {email}")

    return app
