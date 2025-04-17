from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from bson import ObjectId
from extensions import db, mail, serializer

donate_bp = Blueprint('donate', __name__, url_prefix='/donate')

@donate_bp.route("/")
def gam_promise():
    return render_template("donate.html")

@donate_bp.route("/process", methods=["POST"])
def process():
    donor_name = request.form.get("donor_name")
    donor_email = request.form.get("donor_email")
    amount = float(request.form.get("amount"))

    db.donations.insert_one({
        "donor_name": donor_name,
        "donor_email": donor_email,
        "amount": amount,
        "timestamp": datetime.utcnow()
    })

    flash("Thank you for supporting the GAM Promise!", "success")
    return redirect(url_for("donate.gam_promise"))
