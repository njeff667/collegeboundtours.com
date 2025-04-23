# tours/routes.py
from auth.routes import add_new_account_to_db
from bson.objectid import ObjectId
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from student.routes import generate_parent_token, send_parent_consent_email
from extensions import db, mail, serializer
from utils.security import scan_file_for_viruses, handle_exception, role_required, validate_file, allowed_file, upload_to_gcs, sanitize_input
from werkzeug.utils import secure_filename
import os, socket, tempfile

tours_bp = Blueprint("tours", __name__)

def add_reservation_to_cart(user_id, student_id, tour_id):
    try:
        # Force tour_id to ObjectId if necessary
        """if isinstance(tour_id, str):
            tour_id = tour_id"""

        pipeline = [
            {
                '$match': {'_id': tour_id}
            },
            {
                '$lookup': {
                    'from': 'tour_templates',
                    'localField': 'template_id',
                    'foreignField': '_id',
                    'as': 'template_data'
                }
            },
            {
                '$unwind': {
                    'path': '$template_data',
                    'preserveNullAndEmptyArrays': True
                }
            },
            {
                '$lookup': {
                    'from': 'price_tiers',
                    'localField': 'template_data.price_tier_id',  # 🔥 FIXED
                    'foreignField': '_id',
                    'as': 'price_tier_data'
                }
            },
            {
                '$unwind': {
                    'path': '$price_tier_data',
                    'preserveNullAndEmptyArrays': True
                }
            },
            {
                '$project': {
                    '_id': 1,
                    'date': 1,
                    'title': '$template_data.title',
                    'university_names': '$university_names',
                    'price': '$price_tier_data.price'
                }
            }
        ]

        tour_result_cursor = db.tour_instances.aggregate(pipeline)
        tour_result = next(tour_result_cursor, None)

        if not tour_result:
            raise ValueError("Tour not found or invalid aggregation result.")

        price = tour_result.get("price")
        if price is None:
            raise ValueError("Price could not be determined.")

        cart_item = {
            "user_id": user_id,
            "student_id": student_id,
            "added_at": datetime.utcnow(),
            "status": "pending",
            "price": price,
            "reservation_data": tour_result
        }

        if user_id != student_id:
            cart_item["parent_id"] = user_id

        db.cart.insert_one(cart_item)
        db.reservations.insert_one(cart_item)

        return cart_item

    except Exception as e:
        handle_exception(e)
        raise

def build_approval_email(student_name, approve_link):
    try:
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
    except Exception as e:
        handle_exception(e)
        raise

def build_parent_invitation_email(student_name, invite_link):
    try:
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
    except Exception as e:
        handle_exception(e)
        raise

def build_student_invitation_email(parent_name, invite_link):
    """
    Build the HTML email body to invite a student to create an account.

    Args:
        parent_name (str): Name of the parent who initiated the invite.
        invite_link (str): Link for the student to create an account.

    Returns:
        str: HTML content of the email.
    """
    try:
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #004085;">You're Invited to Join College Bound Tours!</h2>
            <p>Hello,</p>

            <p><strong>{parent_name}</strong> has requested to link your account as their student on College Bound Tours.</p>

            <p>Please click the button below to create your student account and approve the connection:</p>

            <p style="text-align: center; margin: 20px 0;">
            <a href="{invite_link}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                Create Student Account
            </a>
            </p>

            <p>If you were not expecting this email, you can safely ignore it.</p>

            <hr>
            <small>This invitation will expire after 24 hours for security purposes.</small>
        </body>
        </html>
        """
    except Exception as e:
        handle_exception(e)
        raise

def calculate_age(birthdate):
    try:
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
    except Exception as e:
        handle_exception(e)
        raise

def get_code_of_conduct_record(user_id):
    """
    Retrieve the Code of Conduct document for a user from the database.

    Args:
        user_id (str): The ID of the user.

    Returns:
        dict or None: The code of conduct record if exists, otherwise None.
    """
    # Example if using MongoDB
    try:
        return db.code_of_conducts.find_one({"user_id": user_id})
    except Exception as e:
        handle_exception(e)
        raise

def get_linked_parent(student_user_id):
    """
    Retrieve the linked parent's ID for a student.

    Args:
        student_user_id (str): The ID of the student.

    Returns:
        str or None: Parent ID if linked, None otherwise.
    """
    try:
        link_record = db.student_parent_links.find_one({
            "student_id": student_user_id
        })

        if link_record:
            return link_record.get("parent_id")
        return None
    except Exception as e:
        handle_exception(e)
        raise

def get_student_name(student_id):
    """
    Fetch student's name for displaying on consent form.
    """
    try:
        student = db.students.find_one({"_id": student_id})
        return student.get("full_name", "Unknown Student")
    except Exception as e:
        handle_exception(e)
        raise

def get_tour_name(tour_id):
    """
    Fetch tour's name for displaying on consent form.
    """
    try:
        tour = db.tours.find_one({"_id": tour_id})
        return tour.get("name", "Unknown Tour")
    except Exception as e:
        handle_exception(e)
        raise

def handle_parent_checklist(user, tour_id):
    try:
        if not isinstance(user.profile, dict):
            flash("Please fill complete your profile before reserving.", "info")
            return redirect(url_for("auth.profile", tour_id=tour_id))
        
        linked_students = get_linked_users(user.id, True)
        if not linked_students:
            flash("You must link a student to your account before proceeding.", "info")
            return redirect(url_for('tours.link_email', tour_id=tour_id))
        
        selected_student_id = request.form.get('student_id')
        if not selected_student_id:
            return render_template('select_student.html', students=linked_students, tour_id=tour_id)
        

        if not has_signed_consent_form(selected_student_id):
            flash("You must sign a consent form for your student.", "info")
            return redirect(url_for('tours.sign_consent', student_id=selected_student_id, tour_id=tour_id))

        if not has_signed_code_of_conduct(user.id, within_days=365):
            flash("You must sign the Code of Conduct.", "info")
            return redirect(url_for('tours.sign_code_of_conduct', tour_id=tour_id))

        if not has_valid_photo_id(user.id):
            flash("You must upload a valid photo ID.", "info")
            return redirect(url_for('tours.upload_photo_id', tour_id=tour_id))

        if request.form.get('is_attending') == 'yes':
            if not has_recent_background_check(user.id, within_days=180):
                flash("You must complete a background check to attend.", "info")
                return redirect(url_for('tours.submit_background_check', tour_id=tour_id))

        add_reservation_to_cart(user.id, selected_student_id, tour_id)
        flash("Reservation added to cart successfully.", "success")
        return redirect(url_for('tours.cart'))
    except Exception as e:
        handle_exception(e)
        raise

@tours_bp.route('/submit_background_check', methods=['GET', 'POST'])
@login_required
@role_required("parent")
def submit_background_check():
    """
    Allow a parent to submit their background check file.
    """
    try:
        if request.method == 'POST':
            file = request.files.get('background_check_file')
            file_status = test_file(file, "background check")
            if file_status == False:
                return redirect(request.url)
            flash("Background check submitted successfully! It is now pending review by an admin.", "sucess")
            return redirect(url_for('tours.tour_checklist'))

        return render_template('submit_background_check.html')

    except Exception as e:
        handle_exception(e)
        raise
    
def handle_student_checklist(user, tour_id):
    try:
        if isinstance(user.profile, dict) and user.profile.get("birthdate"):
            age = calculate_age(user.profile.get("birthdate"))
        else:
            flash("Please fill complete your profile before reserving.", "info")
            return redirect(url_for("auth.profile", tour_id=tour_id))

        if age is None:
            flash("Birthdate is missing from your profile. Please complete your profile first.", "info")
            return redirect(url_for('profile.complete_profile', tour_id=tour_id))  # Example page

        if age >= 18:
            if age > 20:
                flash("Students over 20 are not eligible to participate.", "info")
                return redirect(url_for('home'))

        else:
            if not get_linked_users(user.id, True):
                flash("You must have a parent linked to your account.", "info")
                return redirect(url_for('tours.link_email', tour_id=tour_id))

        if not has_signed_code_of_conduct(user.id, within_days=365):
            flash("You must sign the Code of Conduct.", "info")
            return redirect(url_for('tours.sign_code_of_conduct', tour_id=tour_id))

        if not has_valid_photo_id(user.id):
            flash("You must upload a valid student ID.", "info")
            return redirect(url_for('tours.upload_photo_id', tour_id=tour_id))

        add_reservation_to_cart(user.id, user.id, tour_id)
        flash("Reservation added to cart successfully.")
        return redirect(url_for('tours.cart'))
    except Exception as e:
        handle_exception(e)
        raise

def has_recent_background_check(user_id, within_days=180):
    """
    Check if the user has a valid background check within the required number of days.

    Args:
        user_id (str): The user's ID.
        within_days (int): How recent the background check must be.

    Returns:
        bool: True if background check is recent, False otherwise.
    """
    try:
        record = db.background_checks.find_one({
            "user_id": user_id,
            "status": "approved"  # only count approved checks
        })

        if not record:
            return False

        background_date = record.get("completed_at")
        if not background_date:
            return False

        if isinstance(background_date, str):
            background_date = datetime.strptime(background_date, "%Y-%m-%d")

        cutoff_date = datetime.utcnow() - timedelta(days=within_days)

        return background_date >= cutoff_date
    except Exception as e:
        handle_exception(e)
        raise

def has_linked_parent(student_user_id):
    """
    Check if a student has a linked parent account.

    Args:
        student_user_id (str): The ID of the student.

    Returns:
        bool: True if a linked parent exists, False otherwise.
    """
    try:
        link_record = db.student_parent_links.find_one({
            "student_id": student_user_id
        })

        return link_record is not None
    except Exception as e:
        handle_exception(e)
        raise

def has_valid_photo_id(user_id):
    """
    Check if a user has a valid photo ID uploaded.

    Args:
        user_id (str): ID of the user.

    Returns:
        bool: True if a valid photo ID file exists, False otherwise.
    """
    try:
        user = db.users.find_one({"_id": user_id})

        if not user:
            return False

        profile = user.get("profile", {})
        front_of_id = profile.get("front_of_id_file")
        back_of_id = profile.get("back_of_id_file")

        if not front_of_id or not back_of_id:
            return False

        """# (Optional but recommended) Check if the file physically exists on disk
        UPLOAD_FOLDER = f"uploads_private/{current_user.role}"
        files = [front_of_id, back_of_id]
        for file in files:
            file_path = os.path.join(UPLOAD_FOLDER, file)  # Adjust your uploads path!
            if not os.path.exists(file_path):
                return False"""

        return True
    except Exception as e:
        handle_exception(e)
        raise

def has_signed_code_of_conduct(user_id, within_days=60):
    """
    Check if a user has signed a Code of Conduct form within the given number of days.

    Args:
        user_id (str): The ID of the user.
        within_days (int): Number of days to look back for a valid signature.

    Returns:
        bool: True if signed within timeframe, False otherwise.
    """

    # Query your database - this is just a placeholder function
    try:
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
    except Exception as e:
        handle_exception(e)
        raise

def has_signed_consent_form(student_id, tour_id):
    """
    Check if a student has a signed consent form for a specific tour.

    Args:
        student_id (str): The ID of the student.
        tour_id (str): The ID of the tour.

    Returns:
        bool: True if consent form exists, False otherwise.
    """
    try:
        consent_form = db.consent_forms.find_one({
            "student_id": student_id,
            "tour_id": tour_id
        })

        if consent_form:
            return True

        return False
    except Exception as e:
        handle_exception(e)
        raise

def has_valid_student_id(user_id):
    """
    Check if a student has uploaded a valid student ID.

    Args:
        user_id (str): The ID of the student user.

    Returns:
        bool: True if a student ID file exists, False otherwise.
    """
    try:
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
    except Exception as e:
        handle_exception(e)
        raise

'''def link_students(parent_id, include_pending=False):
    """
    Get all students linked to a parent account.

    Args:
        parent_id (str): The ID of the parent user.
        include_pending (bool): If True, include pending links too.

    Returns:
        list of dicts: List of student records.
    """
    try:
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
    except Exception as e:
        handle_exception(e)
        raise
'''

def get_linked_users(user_id, include_pending=False):
    """
    Get all linked users for the current user.

    Args:
        user_id (str): The ID of the current user (parent or student).
        include_pending (bool): If True, include pending links too.

    Returns:
        list of dicts: List of linked users.
    """
    try:
        current_role = current_user.role  # Detect role at runtime

        if current_role == "parent":
            linked_role = "student"
            current_user_id_field = "parent_id"
            linked_field = "student_email"
        elif current_role == "student":
            linked_role = "parent"
            current_user_id_field = "student_id"
            linked_field = "parent_email"
        else:
            raise ValueError("Invalid user role.")

        # Build the query
        query = {
            current_user_id_field: str(user_id)
        }

        if not include_pending:
            query["status"] = "approved"

        current_user_records = list(db.student_parent_links.find(query))

        # Fetch linked user info
        current_users = []
        for current_user_record in current_user_records:
            linked_user_email = current_user_record.get(linked_field)
            if linked_user_email:
                linked_user = db.users.find_one({
                    "email": linked_user_email,
                    "role": linked_role
                })
                if linked_user:
                    current_users.append({
                        "user_id": linked_user.get("_id"),
                        "user_name": linked_user.get("name", "Unknown"),
                        "link_status": current_user_record.get("status", "unknown"),
                        "linked_date": current_user_record.get("linked_date")
                    })
                else:
                    current_users.append({linked_field: linked_user_email})

        if len(current_users) > 0:
            return current_users
        else:
            return False

    except Exception as e:
        handle_exception(e)
        raise

def safe_get_tour_id():
    return sanitize_input(request.form.get('tour_id')) or sanitize_input(request.args.get('tour_id'))

def save_consent_form(data):
    """
    Save consent form data to database.
    """
    try:
        db.consent_forms.insert_one(data)
    except Exception as e:
        handle_exception(e)
        raise

def send_email(to_email, subject, body):
    """
    Send an email.

    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        body (str): Email body text
    """
    try:
        # You can implement using Flask-Mail, SendGrid, SMTP, etc.
        print(f"Sending email to {to_email}")
        print(f"Subject: {subject}")
        print(f"Body: {body}")
    except Exception as e:
        handle_exception(e)
        raise
    
def test_file(file, file_title):
    try:
        if not file or file.filename == '':
            flash(f"No file selected for the {file_title}.", "danger")
            return False

        if not allowed_file(file.filename):
            flash(f"Invalid file type for the {file_title}. Only JPG, JPEG, PNG, or PDF allowed.", "danger")
            return False

        # Save temporarily
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(temp_path)

        # Virus scan
        if not scan_file_for_viruses(temp_path):
            flash(f"Upload rejected. {file_title} contains a virus or could not be safely scanned.", "danger")
            os.remove(temp_path)
            return False

        # Move to secure folder after passing virus scan
        filename = f"{current_user.id}_photo_id_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
        upload_folder = f"uploads_private/{current_user.role}/{current_user.id}"
        save_path = os.path.join(upload_folder, filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        os.rename(temp_path, save_path)

        # Save file path into DB
        db.users.update_one(
            {"_id": current_user.id},
            {"$set": {
                f"profile.{file_title.replace(' ', '_').lower()}_file": save_path,
                f"profile.{file_title.replace(' ', '_').lower()}_approval": "pending",
                f"profile.{file_title.replace(' ', '_').lower()}_time": datetime.now()
            }}
        )

        return True
    except Exception as e:
        handle_exception(e)
        raise


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
        handle_exception(e)
        flash("Invalid or expired link. Please request a new invitation.", "danger")
        return redirect(url_for('auth.login'))

@tours_bp.route('/cart')
@login_required
def cart():
    try:
        # Find pending cart items for current user
        cart_items = list(db.cart.find({
            "user_id": current_user.id,
            "status": "pending"
        }))

        # (Optional) Fetch student info for display
        user_map = {}
        for item in cart_items:
            user = db.user.find_one({"_id": item.get("_id")})
            if user:
                user_map[item["student_id"]] = user.get("name", "Unknown Student")

        return render_template('cart.html', cart_items=cart_items, user_map=user_map)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/delete_photo_id', methods=['POST'])
@login_required
def delete_photo_id():
    try:
        tour_id = safe_get_tour_id()

        # Fetch student ID file path
        user = db.users.find_one({"_id": current_user.id})
        photo_id_file = user.get("profile", {}).get("photo_id_file")

        # Delete file if it exists
        if photo_id_file and os.path.exists(photo_id_file):
            os.remove(photo_id_file)

        # Remove from database
        db.users.update_one(
            {"_id": current_user.id},
            {"$unset": {"profile.photo_id_file": "", "profile.photo_id_approval": ""}}
        )

        flash("Photo ID deleted successfully. You may upload a new one.", "success")
        return redirect(url_for('tours.upload_photo_id'), tour_id=tour_id)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

'''@tours_bp.route('/link_parent', methods=['GET', 'POST'])
@login_required
@role_required("student")
def link_parent():
    try:
        if request.method == 'POST':
            parent_email = request.form.get('parent_email')

            if not parent_email:
                flash("Please provide your parent's email address.", "danger")
                return redirect(request.url)

            parent_email = parent_email.lower().strip()

            # Block if email belongs to another student
            existing_student = db.users.find_one({
                "email": parent_email,
                "role": "student"
            })

            if existing_student:
                flash("That email belongs to a student account, not a parent.", "danger")
                return redirect(request.url)

            parent_user = db.users.find_one({
                "email": parent_email,
                "role": "parent"
            })

            if parent_user:
                # Parent exists, send approval email
                token = serializer.dumps({
                    "student_id": current_user.id,
                    "parent_id": str(parent_user["_id"]),
                    "parent_email": parent_email
                }, salt="link-parent")

                approve_link = url_for('tours.approve_parent_link', token=token, _external=True)

                send_email(
                    to_email=parent_email,
                    subject="Approve Student Link Request",
                    body=build_approval_email(current_user.name, approve_link)
                )

                # Record pending link immediately
                db.student_parent_links.update_one(
                    {"student_id": current_user.id},
                    {
                        "$set": {
                            "student_id": current_user.id,
                            "parent_id": str(parent_user["_id"]),
                            "parent_email": parent_email,
                            "linked_date": datetime.utcnow(),
                            "status": "pending"  # <<< KEY PART
                        }
                    },
                    upsert=True
                )

                flash("An email has been sent to your parent for approval. You can continue your registration while approval is pending.", "success")
            
            else:
                # Parent doesn't exist, send invite email
                token = serializer.dumps({
                    "student_id": current_user.id,
                    "parent_email": parent_email
                }, salt="invite-parent")

                invite_link = url_for('auth.signup', email=parent_email, invite_token=token, _external=True)

                send_email(
                    to_email=parent_email,
                    subject="Invitation to Join College Bound Tours",
                    body=build_parent_invitation_email(current_user.name, invite_link)
                )

                # Record pending link immediately (no parent_id yet)
                db.student_parent_links.update_one(
                    {"student_id": current_user.id},
                    {
                        "$set": {
                            "student_id": current_user.id,
                            "parent_id": None,
                            "parent_email": parent_email,
                            "linked_date": datetime.utcnow(),
                            "status": "pending"  # <<< KEY PART
                        }
                    },
                    upsert=True
                )

                flash("An invitation email has been sent to your parent. You can continue your registration while approval is pending.", "success")

            # 🚀 Allow student to continue after sending
            return redirect(url_for('tours.tour_checklist'))

        return render_template('link_parent.html')
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
'''

"""@tours_bp.route('/link_student', methods=['GET', 'POST'])
@login_required
@role_required("parent")
def link_student():
    '''
    Allow a parent to link multiple students to their account.
    If student does not exist, send an invitation email to create account.
    Block parent accounts from being linked as students.
    '''
    try:
        if request.method == 'POST':
            student_emails = request.form.getlist('student_email')

            if not student_emails:
                flash("Please enter at least one student's email address.", "danger")
                return redirect(request.url)

            linked_students = []
            errors = []

            for email in student_emails:
                email = email.strip().lower()
                if not email:
                    continue

                # 🔥 FIRST: Block if email belongs to a Parent account
                existing_parent = db.users.find_one({
                    "email": email,
                    "role": "parent"
                })

                if existing_parent:
                    errors.append(f"The email {email} belongs to a parent account, not a student.")
                    continue

                # Then continue normal student checking
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
                        body=build_parent_invitation_email(current_user.name, invite_link)
                    )

                    # Save pending link
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))"""

@tours_bp.route('/link_email', methods=['GET', 'POST'])
@login_required
def link_email():
    """
    Allow a parent to link students, or a student to link a parent.
    """
    try:
        current_role = current_user.role
        tour_id = safe_get_tour_id()

        if current_role == "parent":
            linked_role = "student"
            invite_email_builder = build_student_invitation_email  # assign function
            salt = "invite-student"
        elif current_role == "student":
            linked_role = "parent"
            invite_email_builder = build_parent_invitation_email  # assign function
            salt = "invite-parent"
        else:
            flash("Invalid role for linking.", "danger")
            return redirect(url_for('home'))

        if request.method == 'POST':
            linked_emails = request.form.getlist('linked_email')

            if not linked_emails:
                flash(f"Please enter at least one {linked_role} email address.", "danger")
                return redirect(request.url)

            linked_users = []
            errors = []

            for email in linked_emails:
                email = email.strip().lower()
                if not email:
                    continue

                # Block if same role (parent linking parent or student linking student)
                existing_same_role = db.users.find_one({
                    "email": email,
                    "role": current_role
                })

                if existing_same_role:
                    errors.append(f"The email {email} belongs to a {current_role} account, not a {linked_role}.")
                    continue

                linked_user = db.users.find_one({
                    "email": email,
                    "role": linked_role
                })

                if linked_user:
                    # Already a user
                    existing_link = db.student_parent_links.find_one({
                        f"{linked_role}_id": str(linked_user["_id"]),
                        f"{current_role}_id": str(current_user.id)
                    })

                    if existing_link:
                        errors.append(f"Already linked to {linked_user.get('name', email)}")
                        continue

                    # Create link immediately
                    db.student_parent_links.insert_one({
                        f"{linked_role}_id": str(linked_user["_id"]),
                        f"{current_role}_id": str(current_user.id),
                        "linked_date": datetime.utcnow(),
                        "status": "pending"
                    })

                    linked_users.append(linked_user.get('name', email))
                else:
                    # Send invitation email if user doesn't exist
                    token = serializer.dumps({
                        f"{current_role}_id": str(current_user.id),
                        f"{linked_role}_email": email
                    }, salt=salt)

                    invite_link = url_for('auth.signup', email=email, invite_token=token, _external=True)

                    send_email(
                        to_email=email,
                        subject="Invitation to Join College Bound Tours",
                        body=invite_email_builder(current_user.name, invite_link)
                    )

                    # Save pending link with no linked user yet
                    db.student_parent_links.insert_one({
                        f"{linked_role}_id": None,
                        f"{current_role}_id": str(current_user.id),
                        f"{linked_role}_email": email,
                        "linked_date": datetime.utcnow(),
                        "status": "pending"
                    })

                    linked_users.append(f"Invitation sent to {email}")

            if linked_users:
                flash(f"Successfully processed: {', '.join(linked_users)}", "success")
            if errors:
                for error in errors:
                    flash(error, "danger")
        if current_role == "parent":
            return render_template('link_student.html', linked_role=linked_role, tour_id=tour_id)
        else:
            return render_template('link_parent.html', linked_role=linked_role, tour_id=tour_id)


    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/parent_fill_student_profile', methods=['GET', 'POST'])
@login_required
@role_required("parent")
def parent_fill_student_profile():
    student_id = request.args.get("student_id") or request.form.get("student_id")

    if not student_id:
        flash("No student ID provided.", "danger")
        return redirect(url_for("home"))

    student = db.users.find_one({"_id": ObjectId(student_id), "role": "student"})

    if not student:
        flash("Student account not found.", "danger")
        return redirect(url_for("home"))

    if request.method == "POST":
        # Sanitize and validate fields
        name = sanitize_input(request.form.get("name"))
        grade = sanitize_input(request.form.get("grade"))
        school = sanitize_input(request.form.get("school"))
        birthdate = sanitize_input(request.form.get("birthdate"))

        if not all([name, grade, school, birthdate]):
            flash("All fields are required.", "danger")
            return redirect(request.url)

        if not validate_date(birthdate):
            flash("Invalid birthdate format. Use YYYY-MM-DD.", "danger")
            return redirect(request.url)

        # Save profile
        db.users.update_one(
            {"_id": ObjectId(student_id)},
            {"$set": {
                "name": name,
                "grade": grade,
                "school": school,
                "birthdate": birthdate,
                "profile_complete": True,
                "profile_completed_by": str(current_user.id),
                "profile_completed_at": datetime.utcnow()
            }}
        )

        flash("Student profile updated successfully!", "success")
        return redirect(url_for("tours.tour_checklist", tour_id=request.args.get("tour_id")))

    return render_template("student_profile_form.html", student=student)

@tours_bp.route('/process_selected_students', methods=['POST'])
@login_required
def process_selected_students():
    selected_student_identifiers = student_name = None
    if request.form.getlist('student_identifiers'):
        selected_student_identifiers = sanitize_input(request.form.getlist('student_identifiers'))
    if request.form.get('student_name'):
        student_name = sanitize_input(request.form.get('student_name'))

    if not selected_student_identifiers:
        flash("You must select at least one student.", "danger")
        return redirect(request.url)

    newly_created_student_ids = []

    for selected_student_identifier in selected_student_identifiers:
        if selected_student_identifier:
            student = db.users.find_one({"_id": selected_student_identifier, "role": "student"})
            if not student:
                flash("Selected student not found. Please try again.", "danger")
                return redirect(request.url)
        else:
            if not student_name:
                flash("Please enter the full name for the new student.", "danger")
                return redirect(request.url)

            new_student = add_new_account_to_db(selected_student_identifier, student_name, "student")
            print(new_student)
            new_student_id = db.users.insert_one(new_student).inserted_id
            newly_created_student_ids.append(str(new_student_id))

    if newly_created_student_ids:
        flash("New accounts have been created.", "success")
        return render_template('student_profile_decision.html', newly_created_student_ids=newly_created_student_ids)
    else:
        return redirect(url_for('tours.tour_checklist'))

# Tour Schedule View
@tours_bp.route("/schedule")
def tour_schedule():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

# Tour Reservation
@tours_bp.route("/reserve/<tour_id>", methods=["GET", "POST"])
@login_required
def reserve_tour(tour_id):
    try:
        user_id = current_user.get_id()
        complete_profile = db.users.find_one({"_id": user_id, "profile": {"$exists": True}})
        if not complete_profile:
            return redirect(url_for("auth.profile", tour_id=tour_id))
        
        tour = db.tour_instances.find_one({"_id": tour_id})

        if not tour:
            flash("Tour not found.", "danger")
            return redirect(url_for("tours.tour_schedule"))

        existing = db.reservations.find_one({"user_id": user_id, "tour_id": tour_id})
        if existing:
            flash("Already registered or waitlisted.", "danger")
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

        flash(f"Successfully registered! Status: {status}", "success")
        return redirect(url_for("tours.tour_schedule"))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/sign_consent/<student_id>/<tour_id>', methods=['GET', 'POST'])
@login_required
@role_required("parent")
def sign_consent(student_id, tour_id):
    try:
        if request.method == 'POST':
            signature = request.form.get('signature')
            if not signature:
                flash("Signature is required.", "danger")
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

            flash("Consent form signed successfully.", "success")
            return redirect(url_for('tours.tour_checklist'))  # Or wherever you want to send them next

        # If GET, show the form
        student_name = get_student_name(student_id)
        tour_name = get_tour_name(tour_id)
        return render_template('consent_form.html', student_name=student_name, tour_name=tour_name,
            student_id=student_id, tour_id=tour_id)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route("/tour/<tour_id>")
def tour_details(tour_id):
    try:
        tour = db.tour_instances.find_one({"_id": tour_id})
        #tour["date"] = tour["date"].strftime(") datetime.strptime(date_string, "%m-%d-%Y).date()
        if not tour:
            flash("Tour not found.", "danger")
            return redirect(url_for("tours.tour_schedule"))
        
        if "template_id" in tour:
            template = db.tour_templates.find_one({"_id": tour["template_id"]})
            #print(f"template: {template}")
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
    
@tours_bp.route('/tour_checklist', methods=['GET', 'POST'])
@login_required
def tour_checklist():
    try:
        user = current_user
        tour_id = None
        if request.args.get("tour_id"):
            tour_id = request.args.get("tour_id")

        if user.role == "parent":
            return handle_parent_checklist(user, tour_id)
        elif user.role == "student":
            return handle_student_checklist(user, tour_id)
        else:
            flash("Unknown user role. Please contact support.", "danger")
            return redirect(url_for('home'))
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

# View My Reservations
@tours_bp.route("/my_reservations")
@login_required
def my_reservations():
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

# Complete Profile (After Signup)
@tours_bp.route("/complete-profile", methods=["GET", "POST"])
@login_required
def complete_profile():
    try:
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
            flash("Profile updated.", "success")
            return redirect(url_for("tours.tour_schedule"))

        return render_template("complete_profile.html")
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

# Choose Alternative Tour Dates (Waitlisted Users)
@tours_bp.route("/alternatives/<tour_id>", methods=["GET", "POST"])
@login_required
def choose_alternatives(tour_id):
    try:
        if request.method == "POST":
            selected_tour = sanitize_input(request.form.get("alternative_tour"))
            db.alternate_choices.insert_one({
                "user_id": current_user.get_id(),
                "original_tour_id": ObjectId(tour_id),
                "preferred_alternative_id": ObjectId(selected_tour),
                "timestamp": datetime.utcnow()
            })
            flash("Alternative preference submitted.", "success")
            return redirect(url_for("tours.my_reservations"))

        available = db.tour_instances.find({
            "_id": {"$ne": ObjectId(tour_id)},
            "date": {"$gte": datetime.now()}
        }).sort("date", 1)
        return render_template("choose_alternatives.html", tour_id=tour_id, alternatives=available)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/upload_photo_id', methods=['GET', 'POST'])
@login_required
def upload_photo_id(): 
    try:   
        if request.method == 'POST':
            tour_id = safe_get_tour_id()

            front_id = request.files.get('front_id_file')
            back_id = request.files.get('back_id_file')
            
            front_id_status = test_file(front_id, "front of id")
            back_id_status = test_file(back_id, "back of id")
            if front_id_status == False or back_id_status == False:
                return redirect(request.url)

            flash("Photo ID uploaded successfully. An admin will review for approval.", "success")
            return redirect(url_for('tours.tour_checklist'))
        
        return render_template('upload_photo_id.html', tour_id=tour_id)

    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    """
    Display the checkout page and process finalizing cart items.
    """
    try:
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
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

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
    try:
        user_name =  current_user.name
        tour_id = safe_get_tour_id()

        if request.method == 'POST':

            agree = request.form.get('agree')
            signature = request.form.get('signature')
            if user_name == signature:

                if not agree:
                    flash("You must agree to the Code of Conduct before signing.", "danger")
                    return redirect(request.url)
                if not signature:
                    flash("Signature is required.", "danger")
                    return redirect(request.url)

                # Save Code of Conduct signature to database
                db.code_of_conducts.insert_one({
                    "user_id": current_user.id,
                    "signed_date": datetime.utcnow(),
                    "signature_text": signature,
                    "ip_address": request.remote_addr or socket.gethostbyname(socket.gethostname())
                })

                flash("Code of Conduct signed successfully.", "success")
                return redirect(url_for('tours.tour_checklist'))
            else:
                flash("The signature and name must match. Please try again.", "danger")
        return render_template('code_of_conduct.html', user_name =  user_name)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
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
    "Url": "{{ url_for('tours.upload_photo_id') }}",
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