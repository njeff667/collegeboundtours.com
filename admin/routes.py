# admin/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from utils.security import role_required
from pymongo import MongoClient
from bson.objectid import ObjectId

client = MongoClient("mongodb://localhost:27017/")
db = client["college_bound"]
admin_bp = Blueprint("university_admin", __name__)

@admin_bp.route("/admin/universities")
@login_required
@role_required("admin")
def list_universities():
    universities = list(db.universities.find())
    university_types = list(db.university_types.find())
    type_lookup = {str(t["_id"]): t["label"] for t in university_types}

    for u in universities:
        u["type_labels"] = [type_lookup.get(str(tid), "Unknown") for tid in u.get("type_ids", [])]

    return render_template("admin/universities/list.html", universities=universities)

@admin_bp.route("/admin/universities/<id>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_university(id):
    university = db.universities.find_one({"_id": ObjectId(id)})
    university_types = list(db.university_types.find())

    if request.method == "POST":
        db.universities.update_one({"_id": ObjectId(id)}, {
            "$set": {
                "name": request.form.get("name"),
                "website": request.form.get("website"),
                "visitor_center_address.street": request.form.get("street"),
                "visitor_center_address.city": request.form.get("city"),
                "visitor_center_address.state": request.form.get("state"),
                "visitor_center_address.zip": request.form.get("zip"),
                "type_ids": [ObjectId(tid) for tid in request.form.getlist("type_ids")]
            }
        })
        flash("University updated successfully.")
        return redirect(url_for("university_admin.list_universities"))

    return render_template("admin/universities/edit.html", university=university, university_types=university_types)
