# utils/security.py
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

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
