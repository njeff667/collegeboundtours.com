# Refactored college_bound/app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
from utils.security import sanitize_input


# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# MongoDB setup
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
db = client["college_bound"]

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"

# Blueprint registration
from auth.routes import auth_bp
from tours.routes import tours_bp
from admin.routes import admin_bp
from driver.routes import driver_bp
from parent.routes import parent_bp
from student.routes import student_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(tours_bp, url_prefix="/tours")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(driver_bp, url_prefix="/driver")
app.register_blueprint(parent_bp, url_prefix="/parent")
app.register_blueprint(student_bp, url_prefix="/student")

# Home and static pages
@app.route("/")
def home():
    social_photos = db.photos.find({"approved": True})
    return render_template("home.html", social_photos=social_photos)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET"])
def contact():
    return render_template("contact.html")

@app.route("/contact", methods=["POST"])
def contact_submit():
    from datetime import datetime
    db.messages.insert_one({
        "name": sanitize_input(request.form["name"]),
        "email": sanitize_input(request.form["email"]),
        "message": sanitize_input(request.form["message"]),
        "timestamp": datetime.utcnow()
    })
    flash("Message sent.")
    return redirect(url_for("contact"))

if __name__ == "__main__":
    app.run(debug=True)
