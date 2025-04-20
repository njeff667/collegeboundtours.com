# driver/routes.py
from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required, current_user
from extensions import db, mail, serializer
from utils.security import handle_exception, role_required
from bson.objectid import ObjectId
from datetime import datetime

driver_bp = Blueprint("driver", __name__)

@driver_bp.route("/panel")
@login_required
@role_required("driver")
def driver_panel():
    try:
        # Retrieve upcoming tours assigned to the current driver
        tours = list(db.tour_instances.find({
            "driver_id": ObjectId(current_user.get_id()),
            "date": {"$gte": datetime.utcnow()}
        }).sort("date", 1))

        return render_template("dashboards/driver.html", tours=tours)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
