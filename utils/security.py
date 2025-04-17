# utils/security.py
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
import os
from google.cloud import storage

def sanitize_input(value):
    if not value:
        return ""
    return str(value).strip()

def role_required(required_role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("You must be logged in to access this page.", "warning")
                return redirect(url_for("auth.login"))
            if getattr(current_user, "role", None) != required_role:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("home"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file):
    if file and allowed_file(file.filename):
        return True
    return False

def upload_to_gcs(file, filename, bucket_name="your-gcs-bucket-name"):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_file(file, content_type=file.content_type)
    blob.make_public()
    return blob.public_url
