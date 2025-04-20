# admin/routes.py
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.security import handle_exception, role_required
from bson.objectid import ObjectId
from extensions import db, mail, serializer
from flask_mail import Message
from datetime import datetime, timedelta
import os

admin_bp = Blueprint("admin", __name__)

@admin_bp.route('/admin/student_ids')
@login_required
def admin_student_ids():
    try:
        if not current_user.is_admin():
            flash("Access denied.")
            return redirect(url_for('home'))

        users = db.users.find({
            "profile.student_id_file": {"$exists": True}
        })

        return render_template('admin_student_ids.html', users=users)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@admin_bp.route("/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():
    try:
        total_users = db.users.count_documents({})
        total_tours = db.tour_instances.count_documents({})
        total_tour_templates = db.tour_templates.count_documents({})
        total_reservations = db.reservations.count_documents({})
        total_university_types = db.university_types.count_documents({})
        total_universities = db.universities.count_documents({})
        unverified_guardians = db.users.count_documents({"role": "parent", "verified": {"$ne": True}})
        pending_medical = db.users.count_documents({"role": "student", "medical_info_submitted": {"$ne": True}})

        stats = {
            "total_users": total_users,
            "total_tours": total_tours,
            "total_tour_templates": total_tour_templates,
            "total_reservations": total_reservations,
            "total_university_types": total_university_types,
            "total_universities": total_universities,
            "unverified_guardians": unverified_guardians,
            "pending_medical": pending_medical
        }

        return render_template("dashboards/admin.html", stats=stats)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@admin_bp.route("/admin/universities")
@login_required
@role_required("admin")
def list_universities():
    try:
        universities = list(db.universities.find())
        university_types = list(db.university_types.find())
        type_lookup = {str(t["_id"]): t["label"] for t in university_types}

        for u in universities:
            u["type_labels"] = [type_lookup.get(str(tid), "Unknown") for tid in u.get("type_ids", [])]

        return render_template("admin/universities/list.html", universities=universities)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@admin_bp.route("/admin/universities/<id>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_university(id):
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
    
@admin_bp.route("/guardian-verification-report")
@login_required
@role_required("admin")
def guardian_verification_report():
    try:
        unverified_reservations = list(db.reservations.find({"parent_verified": {"$ne": True}}))

        student_ids = [res["user_id"] for res in unverified_reservations]
        tour_ids = [res["tour_id"] for res in unverified_reservations]

        users = {str(u["_id"]): u for u in db.users.find({"_id": {"$in": student_ids}})}
        tours = {str(t["_id"]): t for t in db.tour_instances.find({"_id": {"$in": tour_ids}})}

        detailed_list = []
        for res in unverified_reservations:
            student = users.get(str(res["user_id"]))
            tour = tours.get(str(res["tour_id"]))

            detailed_list.append({
                "student_name": student.get("name", "N/A"),
                "tour_title": tour.get("title", "N/A"),
                "tour_date": tour.get("date"),
                "parent_email": res.get("parent_email", "N/A"),
                "reservation_id": str(res["_id"])
            })

        return render_template("admin/guardian_verification_report.html", reservations=detailed_list)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
    
@admin_bp.route("/resend-parent-email/<reservation_id>", methods=["POST"])
@login_required
@role_required("admin")
def resend_parent_email(reservation_id):
    try:
        reservation = db.reservations.find_one({"_id": ObjectId(reservation_id)})
        if not reservation:
            flash("Reservation not found.", "danger")
            return redirect(url_for("admin.guardian_verification_report"))

        user = db.users.find_one({"_id": reservation["user_id"]})
        tour = db.tour_instances.find_one({"_id": reservation["tour_id"]})
        parent_email = reservation.get("parent_email")

        if not user or not tour or not parent_email:
            flash("Missing data to resend email.", "warning")
            return redirect(url_for("admin.guardian_verification_report"))

        last_resent = reservation.get("last_consent_resent")
        if last_resent and datetime.utcnow() - last_resent < timedelta(hours=1):
            flash("This consent email was already resent within the last hour.", "info")
            return redirect(url_for("admin.guardian_verification_report"))

        token = serializer.dumps({
            "student_id": str(user["_id"]),
            "tour_id": str(tour["_id"]),
            "parent_email": parent_email
        })

        link = url_for("parents.confirm_parent", token=token, _external=True)

        msg = Message("Parental Consent Reminder", recipients=[parent_email])
        msg.body = f"""
        Hello,

        This is a reminder to complete your parental consent for:
        Student: {user['name']}
        Tour: {tour.get('title', 'a scheduled tour')} on {tour.get('date', '')}

        Confirm here: {link}

        If you already completed this, thank you. This link expires in 1 hour.
        """
        mail.send(msg)

        db.reservations.update_one(
            {"_id": ObjectId(reservation_id)},
            {"$set": {"last_consent_resent": datetime.utcnow()}}
        )

        flash(f"Consent link resent to {parent_email}", "success")
        return redirect(url_for("admin.guardian_verification_report"))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@admin_bp.route("/guardian-verification-export", methods=["GET"])
@login_required
@role_required("admin")
def guardian_verification_export():
    try:
        unverified = db.reservations.find({"parent_verified": {"$ne": True}})
        data = []
        for res in unverified:
            user = db.users.find_one({"_id": res["user_id"]})
            tour = db.tour_instances.find_one({"_id": res["tour_id"]})
            data.append({
                "student": user.get("name", "N/A"),
                "email": res.get("parent_email", "N/A"),
                "tour": tour.get("title", "N/A"),
                "date": tour.get("date", "N/A"),
                "last_resent": res.get("last_consent_resent", "Never")
            })
        return jsonify(data)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))