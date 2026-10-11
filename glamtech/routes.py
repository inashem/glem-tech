from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import limiter
from .forms import ListingForm, LoginForm, LogoutForm, RegisterForm, ReviewForm
from .models import Listing, ListingFile, Review, User, db
from .storage import InvalidUpload, file_path, save_image

bp = Blueprint("site", __name__)
DUMMY_HASH = generate_password_hash("this-is-not-an-account-password")


@bp.before_app_request
def load_user():
    g.user = db.session.get(User, session["user_id"]) if session.get("user_id") else None


@bp.app_context_processor
def shared_context():
    return {"logout_form": LogoutForm(formdata=None)}


def role_required(role):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("site.login"))
            if g.user.role != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


@bp.get("/")
def home():
    page = request.args.get("page", 1, type=int)
    listings = db.paginate(db.select(Listing).where(Listing.status == "Approved").order_by(Listing.created_at.desc(), Listing.id.desc()), page=page, per_page=12, max_per_page=12)
    return render_template("home.html", listings=listings)


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(email=form.email.data.strip().lower(), password_hash=generate_password_hash(form.password.data), role="seller")
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.email.errors.append("Unable to register with these details. Try signing in.")
        else:
            flash("Seller account created. Sign in to submit your first listing.", "success")
            return redirect(url_for("site.login"))
    return render_template("auth.html", form=form, registering=True)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).where(User.email == form.email.data.strip().lower()))
        valid = check_password_hash(user.password_hash if user else DUMMY_HASH, form.password.data)
        if user and valid:
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            return redirect(url_for("site.queue" if user.role == "staff" else "site.mine"))
        form.password.errors.append("Email or password is incorrect.")
    return render_template("auth.html", form=form, registering=False)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("site.home"))


@bp.get("/seller/listings")
@role_required("seller")
def mine():
    listings = db.paginate(db.select(Listing).where(Listing.seller_id == g.user.id).order_by(Listing.created_at.desc(), Listing.id.desc()), per_page=12, max_per_page=12)
    return render_template("mine.html", listings=listings)


@bp.route("/seller/submit", methods=["GET", "POST"])
@role_required("seller")
@limiter.limit("20 per hour", methods=["POST"])
def submit():
    form = ListingForm()
    for field in (form.title, form.description):
        if field.data:
            field.data = field.data.strip()
    saved = []
    if form.validate_on_submit():
        listing = Listing(seller_id=g.user.id, title=form.title.data, description=form.description.data, price=form.price.data, status="Pending")
        try:
            db.session.add(listing)
            db.session.flush()
            for kind in ("photo", "identity", "payment"):
                upload = getattr(form, kind).data
                if upload and upload.filename:
                    name, size = save_image(upload, kind)
                    saved.append(file_path(kind, name))
                    db.session.add(ListingFile(listing_id=listing.id, kind=kind, storage_name=name, size_bytes=size))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            for path in saved:
                path.unlink(missing_ok=True)
            if isinstance(exc, InvalidUpload):
                flash(str(exc), "error")
            else:
                current_app.logger.exception("Listing storage or database transaction failed")
                abort(503)
        else:
            flash("Listing submitted as Pending. It will appear publicly after staff approval.", "success")
            return redirect(url_for("site.mine"))
    return render_template("submit.html", form=form)


@bp.get("/staff/reviews")
@role_required("staff")
def queue():
    listings = db.paginate(db.select(Listing).where(Listing.status == "Pending").order_by(Listing.created_at, Listing.id), per_page=12, max_per_page=12)
    return render_template("queue.html", listings=listings)


@bp.route("/staff/reviews/<int:listing_id>", methods=["GET", "POST"])
@role_required("staff")
def review(listing_id):
    listing = db.get_or_404(Listing, listing_id)
    form = ReviewForm()
    if form.note.data:
        form.note.data = form.note.data.strip()
    if form.validate_on_submit():
        result = db.session.execute(update(Listing).where(Listing.id == listing.id, Listing.status == "Pending").values(status=form.decision.data))
        if result.rowcount != 1:
            db.session.rollback()
            abort(409)
        db.session.add(Review(listing_id=listing.id, staff_id=g.user.id, decision=form.decision.data, note=form.note.data))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            abort(409)
        flash("Review saved with your staff account and a UTC timestamp.", "success")
        return redirect(url_for("site.queue"))
    return render_template("review.html", listing=listing, form=form)


@bp.get("/photos/<int:file_id>")
def photo(file_id):
    item = db.get_or_404(ListingFile, file_id)
    if item.kind != "photo":
        abort(404)
    listing = item.listing
    allowed = listing.status == "Approved" or (g.user and (g.user.role == "staff" or g.user.id == listing.seller_id))
    if not allowed:
        abort(404)
    path = file_path(item.kind, item.storage_name)
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg", download_name="product.jpg", conditional=False, etag=False)


@bp.get("/private-files/<int:file_id>")
def private_file(file_id):
    if not g.user or g.user.role != "staff":
        abort(403)
    item = db.get_or_404(ListingFile, file_id)
    if item.kind not in {"identity", "payment"}:
        abort(404)
    path = file_path(item.kind, item.storage_name)
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg", as_attachment=True, download_name=f"dummy-{item.kind}-verification.jpg", conditional=False, etag=False)
