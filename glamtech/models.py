from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="seller")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (CheckConstraint("role IN ('seller', 'staff')", name="valid_role"),)


class Listing(db.Model):
    __tablename__ = "listings"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="Pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    seller = db.relationship(User)
    files = db.relationship("ListingFile", back_populates="listing", order_by="ListingFile.id")
    reviews = db.relationship("Review", back_populates="listing", order_by="Review.id")
    __table_args__ = (
        CheckConstraint("status IN ('Pending', 'Approved', 'Rejected')", name="valid_status"),
        CheckConstraint("price > 0 AND price <= 9999999999.99", name="valid_price"),
        CheckConstraint("length(title) BETWEEN 3 AND 120", name="valid_title"),
        CheckConstraint("length(description) BETWEEN 10 AND 4000", name="valid_description"),
    )


class ListingFile(db.Model):
    __tablename__ = "listing_files"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    storage_name = db.Column(db.String(40), nullable=False, unique=True)
    mime_type = db.Column(db.String(30), nullable=False, default="image/jpeg")
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    listing = db.relationship(Listing, back_populates="files")
    __table_args__ = (
        CheckConstraint("kind IN ('photo', 'identity', 'payment')", name="valid_file_kind"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="valid_file_size"),
        CheckConstraint("mime_type = 'image/jpeg'", name="valid_file_mime"),
        UniqueConstraint("listing_id", "kind", name="one_file_per_kind"),
    )


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False, unique=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decision = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(500), nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    listing = db.relationship(Listing, back_populates="reviews")
    staff = db.relationship(User)
    __table_args__ = (
        CheckConstraint("decision IN ('Approved', 'Rejected')", name="valid_decision"),
        CheckConstraint("length(note) BETWEEN 3 AND 500", name="valid_review_note"),
    )
