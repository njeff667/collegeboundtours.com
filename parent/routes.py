# parent/routes.py
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from pymongo import MongoClient
from utils.security import role_required
from bson.objectid import ObjectId

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
parent_bp = Blueprint("parent", __name__)

@parent_bp.route("/dashboard")
@login_required
@role_required("parent")
def parent_dashboard():
    # Find reservations associated with this parent's student(s)
    reservations = list(db.reservations.aggregate([
        {"$match": {"parent_id": ObjectId(current_user.get_id())}},
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
