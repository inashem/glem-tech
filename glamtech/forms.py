from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DecimalField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Regexp, StopValidation, ValidationError


def valid_price(form, field):
    if field.data is None or not field.data.is_finite():
        raise StopValidation("Enter a finite price.")
    if field.data.as_tuple().exponent < -2:
        raise ValidationError("Use at most two decimal places.")


class LoginForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Length(max=254), Regexp(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", message="Enter a valid email address.")])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])


class RegisterForm(LoginForm):
    password = PasswordField("Password (12–128 characters)", validators=[DataRequired(), Length(min=12, max=128)])


class ListingForm(FlaskForm):
    title = StringField("Product title", validators=[DataRequired(), Length(min=3, max=120)])
    description = TextAreaField("Description", validators=[DataRequired(), Length(min=10, max=4000)])
    price = DecimalField("Price (NAD)", places=None, validators=[InputRequired(), valid_price, NumberRange(min=0.01, max=9999999999.99)])
    photo = FileField("Product photo", validators=[FileRequired(), FileAllowed(["jpg", "jpeg", "png"], "Upload a JPEG or PNG image.")])
    identity = FileField("Dummy identity verification image (optional)", validators=[FileAllowed(["jpg", "jpeg", "png"])])
    payment = FileField("Dummy payment verification image (optional)", validators=[FileAllowed(["jpg", "jpeg", "png"])])


class ReviewForm(FlaskForm):
    decision = SelectField("Decision", choices=[("Approved", "Approve"), ("Rejected", "Reject")], validators=[DataRequired()])
    note = TextAreaField("Review note (shown to seller)", validators=[DataRequired(), Length(min=3, max=500)])


class LogoutForm(FlaskForm):
    pass
