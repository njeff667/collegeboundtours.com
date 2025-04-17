# parent/routes.py
from bson import ObjectId
from extensions import db  # assuming you initialized db in an extensions.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import db, mail, serializer
from utils.security import role_required, validate_file, allowed_file, upload_to_gcs
from werkzeug.utils import secure_filename
import os
import datetime

parent_bp = Blueprint("parent", __name__)

@parent_bp.route("/dashboard")
@login_required
@role_required("parent")
def parent_dashboard():
    user_id = str(current_user.get_id())
    # Find reservations associated with this parent's student(s)
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

    return render_template("dashboards/parent.html", reservations=reservations)

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

