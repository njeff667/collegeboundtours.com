# tours/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from bson.objectid import ObjectId
from datetime import datetime
from pymongo import MongoClient
from utils.security import sanitize_input

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
tours_bp = Blueprint("tours", __name__)

# Tour Schedule View
@tours_bp.route("/schedule")
def tour_schedule():
    current_date = datetime.now()
    formatted_date = current_date.strftime("%Y-%m-%d")
    upcoming_tours = list(db.tour_instances.find({
        "date": {"$gte": formatted_date}
    }).sort("date", 1))
    print=upcoming_tours
    return render_template("tour_schedule.html", tours=upcoming_tours)

# Tour Reservation
@tours_bp.route("/reserve/<tour_id>", methods=["POST"])
@login_required
def reserve_tour(tour_id):
    user_id = current_user.get_id()
    tour = db.tour_instances.find_one({"_id": ObjectId(tour_id)})

    if not tour:
        flash("Tour not found.")
        return redirect(url_for("tours.tour_schedule"))

    existing = db.reservations.find_one({"user_id": ObjectId(user_id), "tour_id": ObjectId(tour_id)})
    if existing:
        flash("Already registered or waitlisted.")
        return redirect(url_for("tours.tour_schedule"))

    capacity = tour.get("capacity", 13)
    registered = tour.get("registered", 0)
    status = "Confirmed" if registered < capacity else "Waitlisted"

    db.reservations.insert_one({
        "user_id": ObjectId(user_id),
        "tour_id": ObjectId(tour_id),
        "status": status,
        "timestamp": datetime.utcnow()
    })

    if status == "Confirmed":
        db.tour_instances.update_one({"_id": ObjectId(tour_id)}, {"$inc": {"registered": 1}})

    flash(f"Successfully registered! Status: {status}")
    return redirect(url_for("tours.tour_schedule"))

# View My Reservations
@tours_bp.route("/my")
@login_required
def my_reservations():
    pipeline = [
        {"$match": {"user_id": ObjectId(current_user.get_id())}},
        {"$lookup": {
            "from": "tour_instances",
            "localField": "tour_id",
            "foreignField": "_id",
            "as": "tour"
        }},
        {"$unwind": "$tour"},
        {"$sort": {"tour.date": 1}}
    ]
    reservations = db.reservations.aggregate(pipeline)
    return render_template("my_reservations.html", reservations=reservations)

# Complete Profile (After Signup)
@tours_bp.route("/complete-profile", methods=["GET", "POST"])
@login_required
def complete_profile():
    if request.method == "POST":
        phone = sanitize_input(request.form.get("phone"))
        grade = sanitize_input(request.form.get("grade"))
        school = sanitize_input(request.form.get("school"))

        db.users.update_one(
            {"_id": ObjectId(current_user.get_id())},
            {"$set": {
                "phone": phone,
                "grade": grade,
                "school": school,
                "profile_complete": True
            }}
        )
        flash("Profile updated.")
        return redirect(url_for("tours.tour_schedule"))

    return render_template("complete_profile.html")

# Choose Alternative Tour Dates (Waitlisted Users)
@tours_bp.route("/alternatives/<tour_id>", methods=["GET", "POST"])
@login_required
def choose_alternatives(tour_id):
    if request.method == "POST":
        selected_tour = sanitize_input(request.form.get("alternative_tour"))
        db.alternate_choices.insert_one({
            "user_id": ObjectId(current_user.get_id()),
            "original_tour_id": ObjectId(tour_id),
            "preferred_alternative_id": ObjectId(selected_tour),
            "timestamp": datetime.utcnow()
        })
        flash("Alternative preference submitted.")
        return redirect(url_for("tours.my_reservations"))

    available = db.tour_instances.find({
        "_id": {"$ne": ObjectId(tour_id)},
        "date": {"$gte": datetime.now()}
    }).sort("date", 1)
    return render_template("choose_alternatives.html", tour_id=tour_id, alternatives=available)