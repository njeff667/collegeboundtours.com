# tours/routes.py
from bson.objectid import ObjectId
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from student.routes import generate_parent_token, send_parent_consent_email
from extensions import db, mail, serializer
from utils.security import role_required, validate_file, allowed_file, upload_to_gcs, sanitize_input
from werkzeug.utils import secure_filename
import os, socket

tours_bp = Blueprint("tours", __name__)

from datetime import datetime

def add_reservation_to_cart(user_id, student_id):
    """
    Add a reservation to the user's cart.

    Args:
        user_id (str): ID of the logged-in user.
        student_id (str): ID of the student for whom the reservation is made.

    Returns:
        None
    """
    cart_item = {
        "user_id": user_id,
        "student_id": student_id,
        "added_at": datetime.utcnow(),
        "status": "pending",  # pending payment or confirmation
        "reservation_data": {
            # Optional: Add more fields like selected tour, number of guests, etc.
        }
    }

    db.cart.insert_one(cart_item)

def build_approval_email(student_name, approve_link):
    return f"""
    <html>
      <body>
        <h2>Approve Link Request from {student_name}</h2>
        <p>Hello,</p>
        <p>{student_name} has requested to link your account as their parent or guardian.</p>
        <p>Please click the link below to approve the connection:</p>
        <p><a href="{approve_link}">Approve Student Link</a></p>
        <p>If you do not recognize this request, please ignore this email.</p>
      </body>
    </html>
    """

def build_invitation_email(student_name, invite_link):
    return f"""
    <html>
      <body>
        <h2>You're Invited to Join College Bound Tours!</h2>
        <p>Hello,</p>
        <p>{student_name} has requested to link your account as their parent or guardian.</p>
        <p>Please click the link below to create your parent account and approve the connection:</p>
        <p><a href="{invite_link}">Create Parent Account</a></p>
        <p>If you did not expect this email, you may safely ignore it.</p>
      </body>
    </html>
    """

def calculate_age(birthdate):
    if not birthdate:
        return None
    if isinstance(birthdate, str):
        # try to parse string to date if needed
        try:
            birthdate = datetime.strptime(birthdate, "%Y-%m-%d").date()
        except ValueError:
            return None

    today = date.today()
    age = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        age -= 1
    return age

def get_code_of_conduct_record(user_id):
    """
    Retrieve the Code of Conduct document for a user from the database.

    Args:
        user_id (str): The ID of the user.

    Returns:
        dict or None: The code of conduct record if exists, otherwise None.
    """
    # Example if using MongoDB
    return db.code_of_conducts.find_one({"user_id": user_id})

def get_linked_parent(student_user_id):
    """
    Retrieve the linked parent's ID for a student.

    Args:
        student_user_id (str): The ID of the student.

    Returns:
        str or None: Parent ID if linked, None otherwise.
    """
    link_record = db.student_parent_links.find_one({
        "student_id": student_user_id
    })

    if link_record:
        return link_record.get("parent_id")
    return None

def get_student_name(student_id):
    """
    Fetch student's name for displaying on consent form.
    """
    student = db.students.find_one({"_id": student_id})
    return student.get("full_name", "Unknown Student")

def get_tour_name(tour_id):
    """
    Fetch tour's name for displaying on consent form.
    """
    tour = db.tours.find_one({"_id": tour_id})
    return tour.get("name", "Unknown Tour")

def handle_parent_checklist(user):
    linked_students = link_students(user.id)
    if not linked_students:
        flash("You must link a student to your account before proceeding.")
        return redirect(url_for('tours.link_student'))
    
    selected_student_id = request.form.get('student_id')
    if not selected_student_id:
        return render_template('select_student.html', students=linked_students)

    if not has_signed_consent_form(selected_student_id):
        flash("You must sign a consent form for your student.")
        return redirect(url_for('tours.sign_consent', student_id=selected_student_id))

    if not has_signed_code_of_conduct(user.id, within_days=365):
        flash("You must sign the Code of Conduct.")
        return redirect(url_for('tours.sign_code_of_conduct'))

    if not has_valid_photo_id(user.id):
        flash("You must upload a valid photo ID.")
        return redirect(url_for('tours.upload_photo_id'))

    if request.form.get('is_attending') == 'yes':
        if not has_recent_background_check(user.id, within_days=180):
            flash("You must complete a background check to attend.")
            return redirect(url_for('tours.submit_background_check'))

    add_reservation_to_cart(user.id, selected_student_id)
    flash("Reservation added to cart successfully.")
    return redirect(url_for('tours.cart'))

def handle_student_checklist(user):
    if isinstance(user.profile, dict) and user.profile.get("birthdate"):
        age = calculate_age(user.profile.get("birthdate"))
    else:
        flash("Please fill complete your profile before reserving.", "error")
        return redirect(url_for("auth.profile"))

    if age is None:
        flash("Birthdate is missing from your profile. Please complete your profile first.")
        return redirect(url_for('profile.complete_profile'))  # Example page

    if age >= 18:
        if age > 19:
            flash("Students over 19 are not eligible to participate.")
            return redirect(url_for('home'))

        if not has_signed_code_of_conduct(user.id, within_days=365):
            flash("You must sign the Code of Conduct.")
            return redirect(url_for('tours.sign_code_of_conduct'))

        if not has_valid_student_id(user.id):
            flash("You must upload a valid student ID.")
            return redirect(url_for('tours.upload_student_id'))
    else:
        if not has_linked_parent(user.id):
            flash("You must have a parent linked to your account.")
            return redirect(url_for('tours.link_parent'))

        if not has_signed_code_of_conduct(user.id, within_days=365):
            flash("You must sign the Code of Conduct.")
            return redirect(url_for('tours.sign_code_of_conduct'))

    add_reservation_to_cart(user.id, user.id)
    flash("Reservation added to cart successfully.")
    return redirect(url_for('tours.cart'))

def has_linked_parent(student_user_id):
    """
    Check if a student has a linked parent account.

    Args:
        student_user_id (str): The ID of the student.

    Returns:
        bool: True if a linked parent exists, False otherwise.
    """
    link_record = db.student_parent_links.find_one({
        "student_id": student_user_id
    })

    return link_record is not None

def has_signed_code_of_conduct(user_id, within_days=365):
    """
    Check if a user has signed a Code of Conduct form within the given number of days.

    Args:
        user_id (str): The ID of the user.
        within_days (int): Number of days to look back for a valid signature.

    Returns:
        bool: True if signed within timeframe, False otherwise.
    """

    # Query your database - this is just a placeholder function
    code_of_conduct_record = get_code_of_conduct_record(user_id)

    if not code_of_conduct_record:
        return False

    signed_date = code_of_conduct_record.get("signed_date")
    if not signed_date:
        return False

    # If signed_date is a string, parse it
    if isinstance(signed_date, str):
        try:
            signed_date = datetime.strptime(signed_date, "%Y-%m-%d")
        except ValueError:
            return False

    # Calculate if signed_date is within range
    cutoff_date = datetime.now() - timedelta(days=within_days)
    return signed_date >= cutoff_date

from datetime import datetime

def has_signed_consent_form(student_id, tour_id):
    """
    Check if a student has a signed consent form for a specific tour.

    Args:
        student_id (str): The ID of the student.
        tour_id (str): The ID of the tour.

    Returns:
        bool: True if consent form exists, False otherwise.
    """
    consent_form = db.consent_forms.find_one({
        "student_id": student_id,
        "tour_id": tour_id
    })

    if consent_form:
        return True

    return False

def has_valid_student_id(user_id):
    """
    Check if a student has uploaded a valid student ID.

    Args:
        user_id (str): The ID of the student user.

    Returns:
        bool: True if a student ID file exists, False otherwise.
    """
    # Step 1: Get user's profile
    user = db.users.find_one({"_id": user_id})
    if not user:
        return False

    profile = user.get("profile", {})
    student_id_file = profile.get("student_id_file")

    print(f"student_id_file: {student_id_file}")

    # Step 2: Check if student_id_file exists in database
    if not student_id_file:
        return False

    #### FIGURE OUT HOW TO DO THIS WITH MY STORAGE. NOT SAVING
    """# Step 3: (Optional but smart) Check if the file exists on disk/server
    file_path = os.path.join("path_to_student_id_uploads_folder", student_id_file)  # adjust path!
    if not os.path.exists(file_path):
        return False"""

    # If all checks passed
    return True

def link_students(parent_id, include_pending=False):
    """
    Get all students linked to a parent account.

    Args:
        parent_id (str): The ID of the parent user.
        include_pending (bool): If True, include pending links too.

    Returns:
        list of dicts: List of student records.
    """
    query = {
        "parent_id": parent_id
    }

    if not include_pending:
        query["status"] = "approved"

    link_records = list(db.student_parent_links.find(query))

    # Now fetch actual student info
    students = []
    for link in link_records:
        student_id = link.get("student_id")
        if student_id:
            student = db.users.find_one({
                "_id": student_id,
                "role": "student"
            })
            if student:
                students.append({
                    "student_id": student.get("_id"),
                    "student_name": student.get("name", "Unknown Student"),
                    "link_status": link.get("status", "unknown"),
                    "linked_date": link.get("linked_date")
                })

    return students

def save_consent_form(data):
    """
    Save consent form data to database.
    """
    db.consent_forms.insert_one(data)

def send_email(to_email, subject, body):
    """
    Send an email.

    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        body (str): Email body text
    """
    # You can implement using Flask-Mail, SendGrid, SMTP, etc.
    print(f"Sending email to {to_email}")
    print(f"Subject: {subject}")
    print(f"Body: {body}")

@tours_bp.route('/approve_parent_link/<token>')
def approve_parent_link(token):
    try:
        data = serializer.loads(token, salt="link-parent", max_age=86400)  # token expires after 24 hrs
        student_id = data["student_id"]
        parent_id = data["parent_id"]

        # Check if already linked
        existing_link = db.student_parent_links.find_one({
            "student_id": student_id,
            "parent_id": parent_id
        })

        if existing_link:
            flash("You are already linked to this student.", "info")
            return redirect(url_for('auth.login'))  # or parent dashboard

        # Save the new link
        db.student_parent_links.insert_one({
            "student_id": student_id,
            "parent_id": parent_id,
            "linked_date": datetime.utcnow()
        })

        flash("You have successfully linked to your student.", "success")
        return redirect(url_for('auth.login'))  # or parent dashboard

    except Exception as e:
        flash("Invalid or expired link. Please request a new invitation.", "danger")
        return redirect(url_for('auth.login'))

@tours_bp.route('/cart')
@login_required
def cart():
    # Find pending cart items for current user
    cart_items = list(db.cart.find({
        "user_id": current_user.id,
        "status": "pending"
    }))

    # (Optional) Fetch student info for display
    student_map = {}
    for item in cart_items:
        student = db.students.find_one({"_id": item.get("student_id")})
        if student:
            student_map[item["student_id"]] = student.get("full_name", "Unknown Student")

    return render_template('cart.html', cart_items=cart_items, student_map=student_map)

@tours_bp.route('/delete_student_id', methods=['POST'])
@login_required
@role_required('student')
def delete_student_id():
    # Fetch student ID file path
    user = db.users.find_one({"_id": current_user.id})
    student_id_file = user.get("profile", {}).get("student_id_file")

    # Delete file if it exists
    if student_id_file and os.path.exists(student_id_file):
        os.remove(student_id_file)

    # Remove from database
    db.users.update_one(
        {"_id": current_user.id},
        {"$unset": {"profile.student_id_file": ""}}
    )

    flash('Student ID deleted successfully. You may upload a new one.')
    return redirect(url_for('tours.upload_student_id'))

@tours_bp.route('/link_student', methods=['GET', 'POST'])
@login_required
def link_student():
    """
    Allow a parent to link multiple students to their account.
    If student does not exist, send an invitation email to create account.
    """
    from your_database_setup import db
    from bson import ObjectId

    if not current_user.is_parent():
        flash("Only parents can link students.", "warning")
        return redirect(url_for('home'))

    if request.method == 'POST':
        student_emails = request.form.getlist('student_email')

        if not student_emails:
            flash("Please enter at least one student's email address.", "warning")
            return redirect(request.url)

        linked_students = []
        errors = []

        for email in student_emails:
            email = email.strip().lower()
            if not email:
                continue

            student_user = db.users.find_one({
                "email": email,
                "role": "student"
            })

            if student_user:
                # Student found
                existing_link = db.student_parent_links.find_one({
                    "student_id": str(student_user["_id"]),
                    "parent_id": current_user.id
                })

                if existing_link:
                    errors.append(f"Already linked to {student_user.get('name', email)}")
                    continue

                # Create link immediately
                db.student_parent_links.insert_one({
                    "student_id": str(student_user["_id"]),
                    "parent_id": str(current_user.id),
                    "linked_date": datetime.utcnow(),
                    "status": "pending"
                })

                linked_students.append(student_user.get('name', email))
            else:
                # Student not found: send invitation
                token = serializer.dumps({
                    "parent_id": current_user.id,
                    "student_email": email
                }, salt="invite-student")

                invite_link = url_for('auth.signup', email=email, invite_token=token, _external=True)

                send_email(
                    to_email=email,
                    subject="Invitation to Join College Bound Tours",
                    body=build_student_invitation_email(current_user.name, invite_link)
                )

                # Record a pending link even if student hasn't registered yet
                db.student_parent_links.insert_one({
                    "student_id": None,
                    "parent_id": str(current_user.id),
                    "parent_email": email,
                    "linked_date": datetime.utcnow(),
                    "status": "pending"
                })

                linked_students.append(f"Invitation sent to {email}")

        if linked_students:
            flash(f"Successfully processed: {', '.join(linked_students)}", "success")
        if errors:
            for error in errors:
                flash(error, "danger")

        return redirect(url_for('tours.link_student'))

    return render_template('link_student.html')

# Tour Schedule View
@tours_bp.route("/schedule")
def tour_schedule():
    current_date = datetime.now()
    formatted_date = current_date.strftime("%Y-%m-%d")
    upcoming_tours = list(db.tour_instances.find({
        "date": {"$gte": formatted_date}
    }).sort("date", 1))
    for upcoming_tour in upcoming_tours:
        updated_date = str(upcoming_tour["date"]).split("T", 1)
        upcoming_tour["date"] = updated_date[0]
    initial_date = upcoming_tours[0]["date"]
    return render_template("tour_schedule.html", tours=upcoming_tours, initial_date=initial_date)

# Tour Reservation
@tours_bp.route("/reserve/<tour_id>", methods=["GET", "POST"])
@login_required
def reserve_tour(tour_id):
    user_id = current_user.get_id()
    complete_profile = db.users.find_one({"_id": user_id, "profile": {"$exists": True}})
    if not complete_profile:
        return redirect(url_for("auth.profile", tour_id=tour_id))
    
    tour = db.tour_instances.find_one({"_id": tour_id})

    if not tour:
        flash("Tour not found.", "error")
        return redirect(url_for("tours.tour_schedule"))

    existing = db.reservations.find_one({"user_id": user_id, "tour_id": tour_id})
    if existing:
        flash("Already registered or waitlisted.")
        return redirect(url_for("tours.tour_schedule"))

    capacity = tour.get("capacity", 13)
    registered = tour.get("registered", 0)
    status = "Confirmed" if registered < capacity else "Waitlisted"

    user_id = current_user.get_id()
    student_profile = db.users.find_one({"_id": user_id}) or {}

    # After checking age < 18 and before finalizing reservation
    if student_profile.get("age", 0) < 18:
        token = generate_parent_token(user_id, tour_id, student_profile.get("parent_email"))
        send_parent_consent_email(student_profile.get("parent_email"), token)

        db.reservations.update_one(
            {"user_id": current_user.get_id(), "tour_id": ObjectId(tour_id)},
            {"$set": {"parent_verified": False}}
        )

    db.reservations.insert_one({
        "user_id": current_user.get_id(),
        "tour_id": ObjectId(tour_id),
        "status": status,
        "timestamp": datetime.utcnow()
    })

    if status == "Confirmed":
        db.tour_instances.update_one({"_id": ObjectId(tour_id)}, {"$inc": {"registered": 1}})

    flash(f"Successfully registered! Status: {status}")
    return redirect(url_for("tours.tour_schedule"))

@tours_bp.route('/sign_consent/<student_id>/<tour_id>', methods=['GET', 'POST'])
@login_required
def sign_consent(student_id, tour_id):
    if request.method == 'POST':
        signature = request.form.get('signature')
        if not signature:
            flash("Signature is required.")
            return redirect(request.url)

        consent_data = {
            "student_id": student_id,
            "tour_id": tour_id,
            "signed_by_user_id": current_user.id,
            "signed_date": datetime.utcnow(),
            "signature_text": signature,
            "ip_address": request.remote_addr or socket.gethostbyname(socket.gethostname())
        }

        # Save to database
        save_consent_form(consent_data)

        flash("Consent form signed successfully.")
        return redirect(url_for('tours.tour_checklist'))  # Or wherever you want to send them next

    # If GET, show the form
    student_name = get_student_name(student_id)
    tour_name = get_tour_name(tour_id)
    return render_template('consent_form.html', student_name=student_name, tour_name=tour_name,
                           student_id=student_id, tour_id=tour_id)

@tours_bp.route("/tour/<tour_id>")
def tour_details(tour_id):
    tour = db.tour_instances.find_one({"_id": tour_id})
    #tour["date"] = tour["date"].strftime(") datetime.strptime(date_string, "%m-%d-%Y).date()
    if not tour:
        flash("Tour not found.", "danger")
        return redirect(url_for("tours.tour_schedule"))
    
    if "template_id" in tour:
        template = db.tour_templates.find_one({"_id": tour["template_id"]})
        print(f"template: {template}")
    # Fetch university details
    university_list = []
    if "university_ids" in template:
        for univeristy_id in template["university_ids"]:
            type_list = []
            university = db.universities.find_one({"_id": ObjectId(univeristy_id)}) or {}
            print(f"university: {university}")
            
            if university:                
                for type_id in university["type_ids"]:
                    type = db.university_types.find_one({"_id": type_id}) or {}
                    type_list.append(type["label"])
                university["types"] = type_list
                university_list.append(university)        

    return render_template("tour_details.html", tour=tour, universities=university_list, template=template)

@tours_bp.route('/tour_checklist', methods=['GET', 'POST'])
@login_required
def tour_checklist():
    user = current_user

    if user.role == "parent":
        return handle_parent_checklist(user)
    elif user.role == "student":
        return handle_student_checklist(user)
    else:
        flash("Unknown user role. Please contact support.")
        return redirect(url_for('home'))

# View My Reservations
@tours_bp.route("/my")
@login_required
def my_reservations():
    pipeline = [
        {"$match": {"user_id": current_user.get_id()}},
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
            {"_id": current_user.get_id()},
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
            "user_id": current_user.get_id(),
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

UPLOAD_FOLDER = "static/uploads/student_ids"  # adjust path!

@tours_bp.route('/upload_student_id', methods=['GET', 'POST'])
@login_required
@role_required("student")
def upload_student_id():
    if request.method == 'POST':
        file = request.files.get('student_id_file')

        if not file or file.filename == '':
            flash('No file selected.')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash('Invalid file type. Please upload PNG, JPG, JPEG, or PDF.')
            return redirect(request.url)

        filename = secure_filename(file.filename)
        filename = f"{current_user.id}_studentid_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"

        file_path = os.path.join("static/uploads/student_ids", filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file.save(file_path)

        # Save file path into DB
        db.users.update_one(
            {"_id": current_user.id},
            {"$set": {"profile.student_id_file": file_path}}
        )

        flash('Student ID uploaded successfully!')
        return redirect(url_for('tours.tour_checklist'))

    # GET method - show form + current upload
    user = db.users.find_one({"_id": current_user.id})
    student_id_file = None

    if user:
        profile = user.get("profile", {})
        student_id_file = profile.get("student_id_file", None)

    return render_template('student_id_upload.html', student_id_file=student_id_file)

@tours_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    """
    Display the checkout page and process finalizing cart items.
    """

    if request.method == 'POST':
        # User clicked "Confirm and Submit"
        cart_items = list(db.cart.find({
            "user_id": current_user.id,
            "status": "pending"
        }))

        if not cart_items:
            flash("Your cart is empty. Nothing to checkout.", "warning")
            return redirect(url_for('tours.cart'))

        # Update all cart items to 'confirmed' or 'completed'
        db.cart.update_many(
            {"user_id": current_user.id, "status": "pending"},
            {"$set": {"status": "confirmed", "confirmed_at": datetime.utcnow()}}
        )

        flash("Checkout complete! Your reservations are confirmed.", "success")
        return redirect(url_for('tours.checkout_success'))

    else:
        # GET method: show checkout page
        cart_items = list(db.cart.find({
            "user_id": current_user.id,
            "status": "pending"
        }))

        # (Optional) load student names
        student_map = {}
        for item in cart_items:
            student = db.students.find_one({"_id": item.get("student_id")})
            if student:
                student_map[item["student_id"]] = student.get("full_name", "Unknown Student")

        return render_template('checkout.html', cart_items=cart_items, student_map=student_map)

@tours_bp.route('/remove_from_cart/<cart_id>', methods=['POST'])
@login_required
def remove_from_cart(cart_id):
    """
    Remove a reservation from the user's cart.

    Args:
        cart_id (str): The ID of the cart item to remove.

    Returns:
        Redirects back to the cart page with a flash message.
    """

    try:
        db.cart.delete_one({
            "_id": ObjectId(cart_id),
            "user_id": current_user.id  # Security: Only allow deleting your own cart items
        })

        flash("Reservation removed from your cart.", "success")
    except Exception as e:
        flash(f"Error removing item: {str(e)}", "danger")

    return redirect(url_for('tours.cart'))

@tours_bp.route('/code_of_conduct', methods=['GET', 'POST'])
@login_required
def sign_code_of_conduct():
    if request.method == 'POST':
        agree = request.form.get('agree')
        signature = request.form.get('signature')

        if not agree:
            flash("You must agree to the Code of Conduct before signing.")
            return redirect(request.url)
        if not signature:
            flash("Signature is required.")
            return redirect(request.url)

        # Save Code of Conduct signature to database
        db.code_of_conducts.insert_one({
            "user_id": current_user.id,
            "signed_date": datetime.utcnow(),
            "signature_text": signature,
            "ip_address": request.remote_addr or socket.gethostbyname(socket.gethostname())
        })

        flash("Code of Conduct signed successfully.")
        return redirect(url_for('tours.tour_checklist'))

    return render_template('code_of_conduct.html')
"""[
  {
    "Task": "Account Creation",
    "Status": "complete",
    "Required": true,
    "Descr": "Your account has been created. Welcome to College Bound Tours!",
    "Url": "{{ url_for('auth.login') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Profile Completion",
    "Status": "not started",
    "Required": true,
    "Descr": "Complete your personal profile with basic contact and student details.",
    "Url": "{{ url_for('student.student_profile') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Account Link to Parent",
    "Status": "not started",
    "Required": true,
    "Descr": "If you are a student under 18, your account must be linked to your parent or legal guardian.",
    "Url": "{{ url_for('student.request_link') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Account Link to Student",
    "Status": "not started",
    "Required": true,
    "Descr": "Parents must approve the link between their account and their student's account.",
    "Url": "{{ url_for('parent.link_students') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Reserve Tour Date",
    "Status": "not started",
    "Required": true,
    "Descr": "Select and reserve your tour date to secure your seat.",
    "Url": "{{ url_for('tours.tour_schedule') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Verify Parent ID",
    "Status": "not started",
    "Required": true,
    "Descr": "Parents must upload a government-issued ID.",
    "Url": "{{ url_for('parent.upload_id') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Parental Consent",
    "Status": "not started",
    "Required": true,
    "Descr": "Parents must review and sign the consent form for students to participate in the tour.",
    "Url": "{{ url_for('parent.consent_forms') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Criminal Background Check (If Parent Travels)",
    "Status": "not started",
    "Required": true,
    "Descr": "Required only if the parent will physically attend the tour with the student.",
    "Url": "{{ url_for('parent.background_check') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Verify Student Status",
    "Status": "not started",
    "Required": true,
    "Descr": "Upload a valid Student ID (or State ID if under 18). Seniors over 18 must still provide high school ID.",
    "Url": "{{ url_for('student.upload_student_id') }}",
    "Need_by": "Before"
  },
  {
    "Task": "Parent Signs Itinerary at Dropoff",
    "Status": "not started",
    "Required": true,
    "Descr": "Parents must meet the staff at dropoff, verify the itinerary, and sign the final attendance form.",
    "Url": "{{ url_for('parent.dropoff_confirmation') }}",
    "Need_by": "Before"
  }
]
"""