# Refactored college_bound/app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, current_user
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
from utils.security import sanitize_input
from extensions import db, mail, serializer

# Blueprint registration
from ai.routes import ai_bp
from auth.routes import auth_bp
from tours.routes import tours_bp
from admin.routes import admin_bp
from driver.routes import driver_bp
from operations.routes import operations_bp
from parent.routes import parent_bp
from student.routes import student_bp
from donate.routes import donate_bp
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.contrib.facebook import make_facebook_blueprint, facebook
import extensions
from models.user import User

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=None, default_limits=["30 per hour"])

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__, static_folder="templates/static")
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
app.register_blueprint(ai_bp, url_prefix="/auth")
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(tours_bp, url_prefix="/tours")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(driver_bp, url_prefix="/driver")
app.register_blueprint(operations_bp, url_prefix="/operations")
app.register_blueprint(parent_bp, url_prefix="/parent")
app.register_blueprint(student_bp, url_prefix="/student")
app.register_blueprint(donate_bp, url_prefix="/donate")

from flask_mail import Mail

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@example.com'
app.config['MAIL_PASSWORD'] = 'your_email_password'
app.config['MAIL_DEFAULT_SENDER'] = 'your_email@example.com'

mail = Mail(app)
mail.init_app(app)
limiter.init_app(app)

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"

login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    user_doc = db.users.find_one({"_id": ObjectId(user_id)})
    return User(user_doc) if user_doc else None
    
# Google OAuth Blueprint
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    scope=["profile", "email"],
    redirect_url="/google-callback"
)
app.register_blueprint(google_bp, url_prefix="/login")

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max file size

# Facebook OAuth Blueprint
facebook_bp = make_facebook_blueprint(
    client_id=os.getenv("FACEBOOK_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("FACEBOOK_OAUTH_CLIENT_SECRET"),
    redirect_url="/facebook-callback"
)
app.register_blueprint(facebook_bp, url_prefix="/login")

@app.errorhandler(400)
def bad_request_error(error):
    """
    Handle 400 Bad Request errors with specific messages if possible.
    """
    # Try to get custom error description if available
    error_description = getattr(error, 'description', None)

    return render_template('400.html', error_description=error_description), 400

@app.errorhandler(500)
def internal_error(error):
    # (Optional) Log the error if you want
    app.logger.error(f"Server Error: {error}")
    return render_template('500.html'), 500

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

@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html")

@app.context_processor
def inject_cart_count():

    if current_user.is_authenticated:
        cart_count = db.cart.count_documents({
            "user_id": current_user.id,
            "status": "pending"  # Only show pending items
        })
    else:
        cart_count = 0

    return dict(cart_count=cart_count)

if __name__ == "__main__":
    app.run(debug=True)
