# auth/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from pymongo import MongoClient
from models.user import User
from utils.security import sanitize_input
import uuid

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
auth_bp = Blueprint("auth", __name__)

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
    return render_template("auth/login.html")

@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = sanitize_input(request.form.get("email"))
        password = sanitize_input(request.form.get("password"))
        name = sanitize_input(request.form.get("name"))

        if db.users.find_one({"email": email}):
            flash("Email already registered.")
            return redirect(url_for("auth.signup"))

        user = {
            "_id": uuid.uuid4().hex,
            "email": email,
            "name": name,
            "password": generate_password_hash(password),
            "role": "student"  # Default role
        }
        db.users.insert_one(user)
        flash("Account created. Please log in.")
        return redirect(url_for("auth.login"))
    return render_template("auth/signup.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for("auth.login"))

@auth_bp.route("/profile")
@login_required
def profile():
    return render_template("auth/profile.html", user=current_user)
