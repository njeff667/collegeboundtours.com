# driver/routes.py
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from pymongo import MongoClient
from utils.security import role_required
from bson.objectid import ObjectId

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
driver_bp = Blueprint("driver", __name__)

@driver_bp.route("/panel")
@login_required
@role_required("driver")
def driver_panel():
    # Retrieve upcoming tours assigned to the current driver
    tours = list(db.tour_instances.find({
        "driver_id": ObjectId(current_user.get_id()),
        "date": {"$gte": datetime.utcnow()}
    }).sort("date", 1))

    return render_template("dashboards/driver.html", tours=tours)
