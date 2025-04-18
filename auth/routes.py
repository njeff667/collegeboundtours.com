# auth/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from models.user import User
from utils.security import sanitize_input
from extensions import db, mail, serializer
import re, uuid
# In auth/routes.py
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import current_app as app
from utils.email_verification import send_reset_email, get_serializer

auth_bp = Blueprint("auth", __name__)

def is_strong_password(password):
    return (
        len(password) >= 12 and
        re.search(r'[A-Z]', password) and
        re.search(r'[a-z]', password) and
        re.search(r'[0-9]', password) and
        re.search(r'[\W_]', password)
    )

@auth_bp.route('/apple-login')
def apple_login():
    # Your Sign in with Apple logic
    return redirect("/somewhere")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = sanitize_input(request.form.get("email"))
        password = sanitize_input(request.form.get("password"))
        user = db.users.find_one({"email": email})

        if user and check_password_hash(user["password"], password):
            user_obj = User(user)
            login_user(user_obj)
            return redirect(url_for("tours.tour_schedule"))
        flash("Invalid email or password.")
    return render_template("login.html")

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = sanitize_input(request.form.get("email"))
        password = sanitize_input(request.form.get("password"))
        name = sanitize_input(request.form.get("name"))
        role = str(sanitize_input(request.form.get("role"))).lower()

        if role == "student" or role == "parent":
            print(f"{email} registered as a {role}.")
        else:
            print(f"{email} attempted to register as a {role}, but will now be registered as a student.")
            role = "student"

        # Example usage in your signup route:
        if not is_strong_password(password):
            flash("Password must be at least 12 characters and include upper/lowercase letters, a number, and a symbol.")
            return redirect(url_for("auth.signup"))

        if db.users.find_one({"email": email}):
            flash("Email already registered.")
            return redirect(url_for("auth.signup"))

        user = {
            "_id": uuid.uuid4().hex,
            "email": email,
            "name": name,
            "password": generate_password_hash(password),
            "role": role  # Default role
        }

        db.users.insert_one(user)
        flash("Account created. Please log in.")
        return redirect(url_for("auth.login"))
    return render_template("signup.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for("auth.login"))

@auth_bp.route("/profile")
@login_required
def profile():
    tour_id = None
    if request.args.get("tour_id"):
        print(f'request.args.get("tour_id"): {request.args.get("tour_id")}')
        tour_id = sanitize_input(request.args.get("tour_id"))
        print(f"tour_id: {tour_id}")
        if request.method == "GET":
            if current_user.role == "parent":
                if tour_id:
                    return redirect(url_for("parent.parent_profile", tour_id=tour_id))
                else:
                    return redirect(url_for("parent.parent_profile"))            
            elif current_user.role == "student":
                if tour_id:
                    return redirect(url_for("student.student_profile", tour_id=tour_id))
                else:
                    return redirect(url_for("student.student_profile"))
            elif current_user.role == "admin":
                return redirect(url_for("admin.admin_profile"))
            elif current_user.role == "operations":
                return redirect(url_for("operations.operations_profile"))
            else:
                flash("There was an error redirecting to your profile. Please try again", "error")
                return redirect(url_for("tours.tour_schedule"))
        elif request.method == "POST":
            """
            ADD THE LOGIC FOR SAVING THE PROFILE
            """
            if tour_id:
                return redirect(url_for("tours.tour_schedule", tour_id=tour_id))
            else:
                if current_user.role == "parent":
                    return redirect(url_for("parent.parent_profile"))            
                elif current_user.role == "student":
                    return redirect(url_for("student.student_profile"))
                elif current_user.role == "admin":
                    return redirect(url_for("admin.admin_profile"))
                elif current_user.role == "operations":
                    return redirect(url_for("operations.operations_profile"))

@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_request():
    if request.method == "POST":
        email = sanitize_input(request.form.get("email"))
        user = db.users.find_one({"email": email})
        if user:
            token = s.dumps(email, salt='password-reset')
            send_reset_email(email, token)
            flash("Password reset link sent. Check your email.", "info")
        else:
            flash("Email not found.", "danger")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password_request.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        s = get_serializer()
        email = s.loads(token, salt='password-reset', max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("The reset link is invalid or expired.", "danger")
        return redirect(url_for("auth.reset_password_request"))

    if request.method == "POST":
        new_password = generate_password_hash(sanitize_input(request.form.get("password")))
        db.users.update_one({"email": email}, {"$set": {"password": new_password}})
        flash("Password updated successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password_form.html", token=token)
