# student/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_mail import Message
from utils.security import role_required, sanitize_input
from bson.objectid import ObjectId
from datetime import datetime
import os
from extensions import db, mail, serializer

student_bp = Blueprint("student", __name__)

@student_bp.route("/dashboard")
@login_required
@role_required("student")
def student_dashboard():
    print(current_user.get_id())
    reservations = list(db.reservations.aggregate([
        {"$match": {"user_id": current_user.get_id()}},
        {"$lookup": {
            "from": "tour_instances",
            "localField": "tour_id",
            "foreignField": "_id",
            "as": "tour"
        }},
        {"$unwind": "$tour"},
        {"$match": {"tour.date": {"$gte": datetime.utcnow()}}},
        {"$sort": {"tour.date": 1}}
    ]))

    return render_template("dashboards/student.html", reservations=reservations)

def generate_parent_token(student_id, tour_id, parent_email):
    return serializer.dumps({
        "student_id": str(student_id),
        "tour_id": str(tour_id),
        "parent_email": parent_email
    })

def send_parent_consent_email(parent_email, token):
    link = url_for("parent.confirm_parent", token=token, _external=True)
    msg = Message("Parental Consent Required", recipients=[parent_email])
    msg.body = f"""
    A tour reservation has been initiated for your child.

    Please confirm your consent by visiting the following link:

    {link}

    This link expires in 1 hour. If you did not authorize this request, please disregard this message.
    """
    #mail.send(msg)

@student_bp.route("/profile", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_profile():
    tour_id = None
    if request.args.get("tour_id"):
        tour_id = sanitize_input(request.args.get("tour_id"))
        print(f"tour_id: {tour_id}")
    if request.method == "POST":
        student_data = {
            "user_id": current_user.id,
            "is_high_school_student": sanitize_input(request.form.get("is_high_school_student")),
            "current_school_year": sanitize_input(request.form.get("current_school_year")),
            "new_first_time": sanitize_input(request.form.get("new_first_time")),
            "first_name": sanitize_input(request.form.get("first_name")),
            "middle_name": sanitize_input(request.form.get("middle_name")),
            "last_name": sanitize_input(request.form.get("last_name")),
            "email": sanitize_input(request.form.get("email")),
            "country": sanitize_input(request.form.get("country")),
            "street": sanitize_input(request.form.get("street")),
            "city": sanitize_input(request.form.get("city")),
            "state": sanitize_input(request.form.get("state")),
            "postal_code": sanitize_input(request.form.get("postal_code")),
            "cell_phone": sanitize_input(request.form.get("cell_phone")),
            "text_opt_in": sanitize_input(request.form.get("text_opt_in")),
            "gender": sanitize_input(request.form.get("gender")),
            "birthdate": sanitize_input(request.form.get("birthdate")),
            "graduation_year": sanitize_input(request.form.get("graduation_year")),
            "high_school_name": sanitize_input(request.form.get("high_school_name")),
            "high_school_address": sanitize_input(request.form.get("high_school_address")),
            "hs_city": sanitize_input(request.form.get("hs_city")),
            "hs_state": sanitize_input(request.form.get("hs_state")),
            "hs_postal_code": sanitize_input(request.form.get("hs_postal_code")),
            "ceeb_code": sanitize_input(request.form.get("ceeb_code")),
            "academic_interest": sanitize_input(request.form.get("academic_interest")),
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
        profile=current_user["profile"]
    else:
        profile = ""
    return render_template("student_profile.html", student=profile, is_editable=False if profile else True)
