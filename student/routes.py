# student/routes.py
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from pymongo import MongoClient
from utils.security import role_required
from bson.objectid import ObjectId
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
student_bp = Blueprint("student", __name__)

@student_bp.route("/dashboard")
@login_required
@role_required("student")
def student_dashboard():
    reservations = list(db.reservations.aggregate([
        {"$match": {"user_id": ObjectId(current_user.get_id())}},
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
