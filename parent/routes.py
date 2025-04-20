# parent/routes.py
from bson import ObjectId
from extensions import db  # assuming you initialized db in an extensions.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import db, mail, serializer
from utils.security import handle_exception, role_required, sanitize_input, validate_file, allowed_file, upload_to_gcs
from werkzeug.utils import secure_filename
import os
from datetime import datetime

parent_bp = Blueprint("parent", __name__)

@parent_bp.route("/dashboard")
@login_required
@role_required("parent")
def parent_dashboard():
    try:
        return redirect(url_for("auth.dashboard"))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@parent_bp.route("/confirm/<token>", methods=["GET", "POST"])
@login_required
@role_required("parent")
def confirm_parent(token):
    try:
        data = serializer.loads(token, max_age=3600)
        student_id = data.get("student_id")
        tour_id = data.get("tour_id")
        email = data.get("parent_email")
    except (SignatureExpired, BadSignature):
        flash("Invalid or expired confirmation link.", "danger")
        return redirect(url_for("main.home"))

    if request.method == "POST":
        parent_name = request.form.get("parent_name")
        legal_ack = request.form.get("legal_ack")
        signature = request.form.get("signature")

        if not legal_ack or not signature:
            flash("All consent fields must be completed.", "warning")
            return redirect(request.url)

        file = request.files.get("parent_id")
        if not file or not allowed_file(file.filename):
            flash("A valid ID must be uploaded.", "warning")
            return redirect(request.url)

        filename = secure_filename(file.filename)
        gcs_url = upload_to_gcs(file, filename, folder="parent_ids")

        db.reservations.update_one(
            {"user_id": ObjectId(student_id), "tour_id": ObjectId(tour_id)},
            {"$set": {
                "parent_verified": True,
                "parent_name": parent_name,
                "parent_email": email,
                "parent_id_url": gcs_url,
                "confirmed_at": datetime.datetime.utcnow(),
                "signature": signature
            }}
        )

        flash("Parental consent submitted successfully.", "success")
        return redirect(url_for("main.home"))

    return render_template("parent_confirm.html", email=email)

@parent_bp.route("/profile", methods=["GET", "POST"])
@login_required
@role_required("parent")
def parent_profile():
    tour_id = None
    if request.args.get("tour_id"):
        tour_id = sanitize_input(request.args.get("tour_id"))
        print(f"tour_id: {tour_id}")
    if request.method == "POST":
        student_data = {
            "user_id": current_user.id,
            "first_name": sanitize_input(request.form.get("first_name")),
            "middle_name": sanitize_input(request.form.get("middle_name")),
            "last_name": sanitize_input(request.form.get("last_name")),
            "email": sanitize_input(request.form.get("email")),
            "cell_phone": sanitize_input(request.form.get("cell_phone")),
            "text_opt_in": sanitize_input(request.form.get("text_opt_in")),
            "updated_at": datetime.utcnow()
        }
        
        updated_profile = db.users.update_one(
            {"_id": current_user.id},
            {"$set": {"profile": student_data}},
            upsert=True
        )
        print(updated_profile)

        flash("Profile updated successfully.")
        if tour_id:
            return redirect(url_for("tours.tour_schedule", tour_id=tour_id))
    if current_user.profile:
        #user = db.users.find_one({"_id": current_user.id, "profile": {"$exists": True}}) or {}
        profile=current_user.profile
    else:
        profile = ""
    return render_template("parent_profile.html", parent=profile, is_editable=False if profile else True)
