# auth/routes.py
from bson.objectid import ObjectId
from datetime import datetime
from extensions import db, mail, serializer
from flask import Blueprint, current_app as app, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from models.user import User
from utils.email_verification import send_reset_email, get_serializer
from utils.security import handle_exception, sanitize_input
from werkzeug.security import generate_password_hash, check_password_hash
import re, uuid

auth_bp = Blueprint("auth", __name__)

def is_strong_password(password):
    try:
        return (
            len(password) >= 12 and
            re.search(r'[A-Z]', password) and
            re.search(r'[a-z]', password) and
            re.search(r'[0-9]', password) and
            re.search(r'[\W_]', password)
        )
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route('/apple-login')
def apple_login():
    try:
        # Your Sign in with Apple logic
        return redirect("/somewhere")
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    try:
        user_id = current_user.id
        role = current_user.role
        if role == "parent" or role == "student":
            profile = code_of_conduct = student_parent_links = parent_photo = student_photo = None
            profile_created = signed_code_of_conduct = linked_accounts = parent_photo_uploaded = student_photo_uploaded = False
            user = db.users.find_one({"_id": user_id})
            print(user)
            code_of_conduct = db.code_of_conduct.find_one({"user_id": user_id, "date": {"$gte": datetime.now()}})
            if role == "parent":
                student_parent_links = db.student_parent_links.find({"parent_id": user_id}, {"student_email": 1, "status": 1})
                if "photo_id_approval" in student_parent_links:
                    parent_photo_uploaded = student_parent_links["photo_id_approval"]
            elif role == "student":
                student_parent_links = db.student_parent_links.find({"student_id": user_id}, {"parent_email": 1, "status": 1})
                if "photo_id_approval" in student_parent_links:
                    student_photo_uploaded = student_parent_links["photo_id_approval"]

            if "profile" in user:
                profile_created = True
                if code_of_conduct:
                    signed_code_of_conduct = True
                if student_parent_links:
                    for student_parent_link in student_parent_links:
                        if student_parent_link["status"] == "complete":
                            linked_accounts = student_parent_link
                            if role == "parent":
                                student_profile = db.users.profile.find_one({"_id":student_parent_link["parent_id"] })
                                if "photo_id_approval" in student_profile:
                                    student_photo_uploaded = student_profile["photo_id_approval"]
                            elif role == "student":
                                parent_profile = db.users.profile.find_one({"_id":student_parent_link["student_id"] })
                                if "photo_id_approval" in parent_profile:
                                    parent_photo_uploaded = parent_profile["photo_id_approval"]
                
              
            dashboard = {
                "profile_created": profile_created,
                "signed_code_of_conduct": signed_code_of_conduct,
                "linked_accounts": linked_accounts,
                "parent_photo_uploaded": parent_photo_uploaded,
                "student_photo_uploaded": student_photo_uploaded
            }

            reservations = list(db.reservations.aggregate([
                {"$match": {"parent_id": user_id}},
                {"$lookup": {
                    "from": "tour_instances",
                    "localField": "tour_id",
                    "foreignField": "_id",
                    "as": "tour"
                }},
                {"$unwind": "$tour"},
                {"$sort": {"tour.date": 1}}
            ]))
            if role == "parent":
                return  render_template("dashboards/parent.html", reservations=reservations, dashboard=dashboard)

            elif role == "student":
                return  render_template("dashboards/student.html", reservations=reservations, dashboard=dashboard)
        flash("There was a problem accessing the {role} dashboard", "error")
        return redirect(url_for("home"))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
    
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/logout")
@login_required
def logout():
    try:
        logout_user()
        flash("Logged out successfully.")
        return redirect(url_for("auth.login"))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/profile")
@login_required
def profile():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_request():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        s = get_serializer()
        email = s.loads(token, salt='password-reset', max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("The reset link is invalid or expired.", "danger")
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('auth.reset_password_request'))
    try:
        if request.method == "POST":
            new_password = generate_password_hash(sanitize_input(request.form.get("password")))
            db.users.update_one({"email": email}, {"$set": {"password": new_password}})
            flash("Password updated successfully. Please log in.", "success")
            return redirect(url_for("auth.login"))

        return render_template("auth/reset_password_form.html", token=token)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
