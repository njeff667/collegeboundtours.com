# tours/routes.py
from auth.routes import add_new_account_to_db
from bson.objectid import ObjectId
from bson.timestamp import Timestamp  # For MongoDB's BSON Date type

from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from student.routes import generate_parent_token, send_parent_consent_email
from extensions import db, mail, serializer
from utils.security import allowed_file, handle_exception, role_required, safe_get_parameter, safe_get_parameter_list, sanitize_for_json, sanitize_input, scan_file_for_viruses, upload_to_gcs, validate_file
from werkzeug.utils import secure_filename
import os, json, socket, tempfile

tours_bp = Blueprint("tours", __name__)
def add_reservation_to_cart(user_id, student_ids, tour_id):
    """
    Add one or more reservations to the cart, with seat status logic.

    Args:
        user_id (str): The ID of the parent (or student).
        student_ids (list or str): Single student ID or list of student IDs.
        tour_id (str or ObjectId): ID of the tour instance.

    Returns:
        list: List of reservation/cart items created.
    """
    try:
        tour_id = ObjectId(tour_id) if isinstance(tour_id, str) else tour_id
        if isinstance(student_ids, str):
            student_ids = [student_ids]  # Make it a list for unified processing

        # === Step 1: Fetch tour with pricing info
        pipeline = [
            {'$match': {'_id': tour_id}},
            {'$lookup': {
                'from': 'tour_templates',
                'localField': 'template_id',
                'foreignField': '_id',
                'as': 'template_data'
            }},
            {'$unwind': {
                'path': '$template_data',
                'preserveNullAndEmptyArrays': True
            }},
            {'$lookup': {
                'from': 'price_tiers',
                'localField': 'template_data.price_tier_id',
                'foreignField': '_id',
                'as': 'price_tier_data'
            }},
            {'$unwind': {
                'path': '$price_tier_data',
                'preserveNullAndEmptyArrays': True
            }},
            {'$project': {
                '_id': 1,
                'date': 1,
                'title': '$template_data.title',
                'university_names': '$university_names',
                'price': '$price_tier_data.price',
                'registered': 1,
                'capacity': 1
            }}
        ]

        tour_result = next(db.tour_instances.aggregate(pipeline), None)

        if not tour_result:
            raise ValueError("Tour not found or invalid aggregation result.")

        price = tour_result.get("price")
        capacity = tour_result.get("capacity", 13)
        registered = tour_result.get("registered", 0)

        if price is None:
            raise ValueError("Price could not be determined.")

        available = capacity - registered
        new_confirmed = 0
        created_items = []

        for i, student_id in enumerate(student_ids):
            seat_status = "Confirmed" if i < available else "Waitlisted"
            if seat_status == "Confirmed":
                new_confirmed += 1

            cart_item = {
                "user_id": user_id,
                "student_id": student_id,
                "tour_id": str(tour_id),
                "added_at": datetime.utcnow(),
                "status": "pending",  # cart status
                "seat_status": seat_status,
                "price": price,
                "reservation_data": tour_result
            }

            if user_id != student_id:
                cart_item["parent_id"] = user_id

            db.cart.insert_one(cart_item)
            db.reservations.insert_one(cart_item)
            created_items.append(cart_item)

        # Update the registered count only for confirmed students
        if new_confirmed > 0:
            db.tour_instances.update_one(
                {"_id": tour_id},
                {"$inc": {"registered": new_confirmed}}
            )

        return created_items

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

def get_number_of_slots_available(tour_id):
    try:
        tour_info = db.tour_instances.find_one({"_id": tour_id})
        if tour_info:
            capacity = tour_info["capacity"]
            registered = tour_info["registered"]
            slots_available = int(capacity-registered)
            return slots_available
        else:
            return 0
    except Exception as e:
        handle_exception(e)
        raise

def get_student_name(student_id):
    """
    Fetch student's name for displaying on consent form.
    """
    try:
        student = db.users.find_one({"_id": ObjectId(student_id)})
        return student.get("name", "Unknown Student")
    except Exception as e:
        handle_exception(e)
        raise

def get_tour_name(tour_id):
    """
    Fetch tour's name for displaying on consent form.
    """
    try:
        tour = db.tour_instances.find_one({"_id": tour_id})
        return tour.get("name", "Unknown Tour")
    except Exception as e:
        handle_exception(e)
        raise

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
        elif current_role == "student":
            linked_role = "parent"
        else:
            raise ValueError("Invalid user role.")

        # Build the query
        query = {
            f"{current_role}_id": user_id
        }
        
        if not include_pending:
            query["status"] = "approved"

        current_user_records = list(db.student_parent_links.find(query))

        # Fetch linked user info
        current_users = []
        for current_user_record in current_user_records:
            sanitize_current_user_record = sanitize_for_json(current_user_record)
            linked_user_id = None
            if f"{linked_role}_id" in sanitize_current_user_record:
                linked_user_id = sanitize_current_user_record[f"{linked_role}_id"]

            if linked_user_id:
                linked_user = db.users.find_one({
                    "_id": ObjectId(linked_user_id),
                    "role": linked_role
                })
                print(linked_user)

                if linked_user:
                    current_users.append({
                        f"{linked_role}_id": linked_user_id,
                        f"{linked_role}_email": linked_user.get("email", "unknown"),
                        f"{linked_role}_name": linked_user.get("name", "unknown"),
                    })
            else:
                # fallback to using the email stored in the link record
                current_users.append({
                    f"{linked_role}_email": current_user_record.get(f"{linked_role}_email", "unknown"),
                })

        if len(current_users) > 0:
            #return sanitize_for_json(current_user_records)
            return current_users
        else:
            return []

    except Exception as e:
        handle_exception(e)
        raise

def get_selected_students(user_id, tour_id):
    try:
        selections = db.temporary_selections.find({
            "parent_id": str(user_id),
            "tour_id": str(tour_id)
        })

        student_ids = []
        for selection in selections:
            student_ids.extend(selection.get("student_ids", []))

        return student_ids
    except Exception as e:
        handle_exception(e)
        return []

def handle_parent_checklist(tour_id, slots_available):
    try:
        user_id = str(current_user.id)
        print(f"handle_parent_checklist tour_id: {tour_id}")
        if not isinstance(current_user.profile, dict):
            flash("Please complete your profile before reserving.", "info")
            return redirect(url_for("auth.profile", tour_id=tour_id))
        # ✅ Get all linked students (approved or pending)
        linked_students = get_linked_users(str(user_id), include_pending=True)

        if len(linked_students) < 1:
            flash("You must link a student to your account before proceeding.", "info")
            return redirect(url_for('tours.link_email', tour_id=tour_id))
                
        # ✅ Get previously selected students from temp collection
        selected_students = get_selected_students(user_id, tour_id)
        num_of_selected_students = len(selected_students)

        if num_of_selected_students < 1:
            flash("No students were selected. Please select at least one student before continuing.", "danger")
            return render_template('select_student.html', students=linked_students, tour_id=tour_id)
        elif num_of_selected_students >  slots_available:
            flash(f"There are {slots_available} available slots for this tour. You have selected {num_of_selected_students} student(s), exceeding the limit by {-1*(num_of_selected_students-slots_available)}. Slots are assigned on a first-come, first-served basis. Each student may bring one parent or guardian, but students are prioritized when space is limited.", "danger")
            return render_template('selected_student_waitlist.html', students=linked_students, tour_id=tour_id)   
            """
            *********************************
              THIS HAS NOT BEEN CREATED YET
            *********************************
            """ 
        
        # ✅ Parent Attendence
        parent_attendance_status = has_parent_attendance_status(user_id, tour_id)
        if not parent_attendance_status:
            flash("You must inform if you plan on attending. Note that if you do attend, we will conduct a criminal background check on all adults traveling on the trip with high school students.", "info")
            return redirect(url_for("tours.parent_attendance", tour_id=tour_id))
        elif str(parent_attendance_status).lower() == "yes":
            flash("We have recorded that you will be attending. We will need to conduct a criminal background check on all adults traveling on the trip with high school students.", "info")


        if num_of_selected_students-slots_available < 1 and str(parent_attendance_status).lower() == "yes":
            flash("There are no more avaialbe slots for a parent or guardian. You will not be placed on the waitlist.", "warning")
            waitlist_parent(user_id, "parent")

        # ✅ Consent Form check (parent must consent per student)
        for student_id in selected_students:
            signed_consent_form = has_signed_consent_form(student_id, tour_id, 60)
            if not signed_consent_form:
                flash("You must sign a consent form for each student.", "info")
                return redirect(url_for('tours.sign_consent', student_id=student_id, tour_id=tour_id))

        # ✅ Code of Conduct (parent signs annually)
        signed_code_of_conduct = has_signed_code_of_conduct(user_id, within_days=180)
        if not signed_code_of_conduct:
            flash("You must sign the Code of Conduct.", "info")
            return redirect(url_for('tours.sign_code_of_conduct', tour_id=tour_id))

        # ✅ Upload Parent Photo ID
        valid_photo_id = has_valid_photo_id(user_id, tour_id)
        if not valid_photo_id:
            flash("You must upload a valid photo ID.", "info")
            return redirect(url_for('tours.upload_photo_id', tour_id=tour_id))
               
        recent_background_check = has_recent_background_check(user_id, within_days=180)
        if not recent_background_check:
            flash("You must complete a background check to attend.", "info")
            return redirect(url_for('tours.submit_background_check', tour_id=tour_id))

        # ✅ Reservation step with seat logic
        reservations = add_reservation_to_cart(user_id, selected_student_ids, tour_id)

        flash(f"Reservation(s) added to cart. ({len(reservations)} student(s))", "success")
        return redirect(url_for('tours.cart'))

    except Exception as e:
        handle_exception(e)
        raise

def handle_student_checklist(tour_id, slots_available):
    try:
        user_id = str(current_user.id)
        if isinstance(current_user.profile, dict) and current_user.profile.get("birthdate"):
            age = calculate_age(current_user.profile.get("birthdate"))
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
            if not get_linked_users(user_id, True):
                flash("You must have a parent linked to your account.", "info")
                return redirect(url_for('tours.link_email', tour_id=tour_id))

        if not has_signed_code_of_conduct(user_id, within_days=180):
            flash("You must sign the Code of Conduct.", "info")
            return redirect(url_for('tours.sign_code_of_conduct', tour_id=tour_id))

        if not has_valid_photo_id(user_id):
            flash("You must upload a valid student ID.", "info")
            return redirect(url_for('tours.upload_photo_id', tour_id=tour_id))

        add_reservation_to_cart(user_id, tour_id)
        flash("Reservation added to cart successfully.")
        return redirect(url_for('tours.cart'))
    except Exception as e:
        handle_exception(e)
        raise

def has_parent_attendance_status(user_id, tour_id):
    """
    Check if the parent has made a choice to attend or not.
    """
    try:
        parent_attendance_status = db.temporary_selection. find_one({"parent_id": user_id, "tour_id": tour_id}, {"parent_attendance": 1})
        if parent_attendance_status:
            return parent_attendance_status
        else:
            return False
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

def has_valid_photo_id(user_id, tour_id):
    """
    Check if a user has a valid photo ID uploaded.

    Args:
        user_id (str): ID of the user.

    Returns:
        bool: True if a valid photo ID file exists, False otherwise.
    """
    try:
        user = db.users.find_one({"_id": ObjectId(user_id)})

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
    try:
        code_of_conduct_record = db.code_of_conducts.find_one({"user_id": user_id, "signed_date": {"$gte": datetime.now() -timedelta(days=within_days)}})

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

def has_signed_consent_form(student_id, tour_id, expiration):
    """
    Check if a student has a signed consent form for a specific tour.

    Args:
        student_id (str): The ID of the student.
        tour_id (str): The ID of the tour.

    Returns:
        bool: True if consent form exists, False otherwise.
    """
    try:
        
        print(f"student_id: {student_id}")
        print(f"signed_date: {datetime.now() + timedelta(days=expiration)}")
        print(f"tour_id: {tour_id}")
        consent_form = db.consent_forms.find_one({
            "student_id": str(student_id),
            "tour_id": tour_id,
            "signed_date": {"$gte": datetime.now() - timedelta(days=expiration)}
        })

        print(f"consent_form: {consent_form}")

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
        user = db.users.find_one({"_id": ObjectId(user_id)})
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

def insert_ts_record(students_ids, user_id, tour_id):
    try:
        inserted_ts_record = db.temporary_selections.insert_one({
            "student_ids": students_ids,
            "parent_id": str(user_id),
            "date_added_to_tour": datetime.utcnow(),
            "tour_id": tour_id,
            "status": "pending"
        })
        return inserted_ts_record
    except Exception as e:
        handle_exception(e)
        raise

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
            {"_id": ObjectId(current_user.id)},
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

def waitlist_parent(wait_list_id, wait_list_role):
    try:
        status = db.temporary_selection.update_one({f"{wait_list_role}_id":wait_list_id}, {$set: {"status": "waitlist"}})
        return status
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
        tour_id = safe_get_parameter("tour_id")

        # Fetch student ID file path
        user = db.users.find_one({"_id": ObjectId(current_user.id)})
        photo_id_file = user.get("profile", {}).get("photo_id_file")

        # Delete file if it exists
        if photo_id_file and os.path.exists(photo_id_file):
            os.remove(photo_id_file)

        # Remove from database
        db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$unset": {"profile.photo_id_file": "", "profile.photo_id_approval": ""}}
        )

        flash("Photo ID deleted successfully. You may upload a new one.", "success")
        return redirect(url_for('tours.upload_photo_id'), tour_id=tour_id)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/link_email', methods=['GET', 'POST'])
@login_required
def link_email():
    """
    Allow a parent to link students, or a student to link a parent.
    """
    try:
        current_role = current_user.role
        current_user_id = str(current_user.id)
        tour_id = safe_get_parameter("tour_id")

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
            linked_emails = safe_get_parameter('linked_email')

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
                        f"{linked_role}_id": linked_user["_id"],
                        f"{current_role}_id": current_user.id
                    })

                    if existing_link:
                        errors.append(f"Already linked to {linked_user.get('name', email)}")
                        continue

                    # Create link immediately
                    db.student_parent_links.insert_one({
                        f"{linked_role}_id": linked_user["_id"],
                        f"{current_role}_id": current_user.id,
                        "linked_date": datetime.utcnow(),
                        "status": "pending"
                    })

                    linked_users.append(linked_user.get('name', email))
                else:
                    # Send invitation email if user doesn't exist
                    token = serializer.dumps({
                        f"{current_role}_id": current_user_id,
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
                        f"{current_role}_id": current_user_id,
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

@tours_bp.route('parent_attendance', methods=['GET', 'POST'])
@login_required
@role_required('parent')
def parent_attendance():
    try:
        tour_id = safe_get_parameter("tour_id")
        if request.method == "GET":            
            return render_template("parent_attendance.html", tour_id=tour_id)
        elif request.method == "POST":
            parent_attendance_decison = safe_get_parameter("parent_attendance_decison")
            if not parent_attendance_decison:
                redirect(request.url)
            if str(parent_attendance_decison).lower() == "yes":
                insert_ts_record(None, current_user.id, tour_id)
            return redirect(url_for("tours.tour_checklist", tour_id=tour_id))



    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

@tours_bp.route('/parent_fill_student_profile', methods=['GET', 'POST'])
@login_required
@role_required("parent")
def parent_fill_student_profile():
    student_id = safe_get_parameter("student_id")

    if not student_id:
        flash("No student ID provided.", "danger")
        return redirect(url_for("home"))

    student = db.users.find_one({"_id": student_id, "role": "student"})

    if not student:
        flash("Student account not found.", "danger")
        return redirect(url_for("home"))

    if request.method == "POST":
        # Sanitize and validate fields
        name = safe_get_parameter("name")
        grade = safe_get_parameter("grade")
        school = safe_get_parameter("school")
        birthdate = safe_get_parameter("birthdate")

        if not all([name, grade, school, birthdate]):
            flash("All fields are required.", "danger")
            return redirect(request.url)

        if not validate_date(birthdate):
            flash("Invalid birthdate format. Use YYYY-MM-DD.", "danger")
            return redirect(request.url)

        # Save profile
        db.users.update_one(
            {"_id": student_id},
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
        return redirect(url_for("tours.tour_checklist", tour_id=safe_get_parameter("tour_id")))

    return render_template("student_profile_form.html", student=student)

@tours_bp.route('/process_selected_students', methods=['POST'])
@login_required
def process_selected_students():
    student_name = None
    selected_student_identifiers = safe_get_parameter_list('student_identifiers', ":")
    tour_id = safe_get_parameter("tour_id")
    if not tour_id:
        flash("There were no tour id was selected.", "danger")
        return redirect(url_for("tours.schedule"))

    if not selected_student_identifiers:
        flash("There were no students selected.", "danger")
        return redirect(url_for("tours.tour_checklist", tour_id=tour_id))

    newly_created_student_ids = []
    add_to_temporary_selections = []
    student_index = 1

    for selected_student_identifier in selected_student_identifiers:
        student_identifier = str(selected_student_identifier).split(":")
        student_id = student_identifier[0]
        student_email = student_identifier[1]
        if student_id:
            student = db.users.find_one({"_id": ObjectId(student_id), "role": "student"})
            if not student:
                flash("Selected student not found. Please try again.", "danger")
                return redirect(url_for("tours.tour_checklist", tour_id=tour_id))
            student_on_ts = db.temporary_selection.find_one({"student_ids": {"$in": [student_id]}, "tour_id": tour_id})
            if not student_on_ts:
                add_to_temporary_selections.append(student_id)
        else:            
            student = db.users.find_one({"email": student_email, "role": "student"})
            if not student:
                student_name = safe_get_parameter(f'student_name[{student_index}]')
                if not student_name:
                    flash("Please enter the full name for the new student.", "danger")
                    return redirect(url_for("tours.tour_checklist", tour_id=tour_id))
                new_student_info = add_new_account_to_db(student_email, student_name, "student")
                new_student_id = db.users.insert_one(new_student_info).inserted_id
                print(new_student_id)
                db.student_parent_links.update_one({"student_email": student_email}, {"$set": {"student_id": str(new_student_id)}})
                newly_created_student_ids.append(str(new_student_id))

                flash("New accounts have been created.", "success")
            else:
                flash("The account has already been created, but no profile exists.", "warning")
            add_to_temporary_selections.append(new_student_id)
        student_index += 1    

    if add_to_temporary_selections:
        insert_ts_record(add_to_temporary_selections, current_user.id, tour_id)
    
    if newly_created_student_ids:
        return render_template('student_profile_decision.html', student_ids=newly_created_student_ids)
    else:
        flash("Your selection has been recorded.", "success")
        return redirect(url_for('tours.tour_checklist', tour_id=tour_id))

@tours_bp.route('/student_fill_profile_later', methods=['POST'])
@login_required
@role_required("parent")
def student_fill_profile_later():
    student_ids = safe_get_parameter("student_id")
    tour_id = safe_get_parameter("tour_id")

    if not student_ids:
        flash("No students selected.", "danger")
        return redirect(url_for("home"))

    # Optionally mark that the parent deferred profile completion
    for sid in student_ids:
        db.users.update_one(
            {"_id": ObjectId(sid), "role": "student"},
            {"$set": {
                "profile_deferred": True,
                "profile_deferred_by": str
                (current_user.id),
                "profile_complete": False
            }}
        )

    flash("Student(s) can log in to complete their profile before attending a tour.", "info")
    return redirect(url_for("tours.tour_checklist", tour_id=tour_id))

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
        complete_profile = db.users.find_one({"_id": ObjectId(user_id), "profile": {"$exists": True}})
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

        student_profile = db.users.find_one({"_id": ObjectId(user_id)}) or {}

        # After checking age < 18 and before finalizing reservation
        if student_profile.get("age", 0) < 18:
            token = generate_parent_token(user_id, tour_id, student_profile.get("parent_email"))
            send_parent_consent_email(student_profile.get("parent_email"), token)

            db.reservations.update_one(
                {"user_id": current_user.get_id(), "tour_id": tour_id},
                {"$set": {"parent_verified": False}}
            )

        db.reservations.insert_one({
            "user_id": current_user.get_id(),
            "tour_id": tour_id,
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
        if not student_id:
            student_id = safe_get_parameter("student_id")

        if not tour_id:
            tour_id = safe_get_parameter("tour_id")

        if request.method == "GET":
            tour_instance = db.tour_instances.find_one({"_id": tour_id})
            print(f'tour_instance["date"]: {tour_instance["date"]}')
            tour_date_raw = datetime.fromisoformat(tour_instance["date"])
            tour_date_formatted = tour_date_raw.strftime("%B %d, %Y")
            # If GET, show the form
            print(student_id)
            student_name = get_student_name(student_id)
            tour_name = get_tour_name(tour_id)
            return render_template(
                'consent_form.html',            
                student_name=student_name,
                parent_name = sanitize_for_json(current_user).name,
                tour_name=tour_name,
                tour_date=tour_date_formatted,
                tour_universities=tour_instance["university_names"],
                student_id=student_id, 
                tour_id=tour_id
            )
        elif request.method == 'POST':
            signature = safe_get_parameter('signature')
            name_on_file = safe_get_parameter('name_on_file')
            
            if not signature:
                flash("Signature is required.", "danger")
                return redirect(request.url)
            
            if not name_on_file:
                flash("Something went wrong. The name on file did not appear. Please try again.", "danger")
                return redirect(request.url)

            if signature == name_on_file:
                consent_data = {
                    "student_id": str(student_id),
                    "tour_id": str(tour_id),
                    "signed_by_user_id": str(current_user.id),
                    "signed_date": datetime.utcnow(),
                    "parent_signature_text": signature,
                    "ip_address": request.remote_addr or socket.gethostbyname(socket.gethostname())
                }

                # Save to database
                save_consent_form(consent_data)

                flash("Consent form signed successfully.", "success")
            else:
                flash("The signature for your consent form did not match the name on file.", "danger")
            return redirect(url_for('tours.tour_checklist', tour_id=tour_id))  # Or wherever you want to send them next
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

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
        
        tour_id = safe_get_parameter("tour_id")
        print(f"tour_checklist tour_id: {tour_id}")
        slots_available = get_number_of_slots_available(tour_id)
        if user.role == "parent":
            return handle_parent_checklist(tour_id, slots_available)
        elif user.role == "student":
            return handle_student_checklist(tour_id, slots_available)
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
            phone = safe_get_parameter("phone")
            grade = safe_get_parameter("grade")
            school = safe_get_parameter("school")

            db.users.update_one(
                {"_id": ObjectId(current_user.get_id())},
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
            selected_tour = safe_get_parameter("alternative_tour")
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
        tour_id = safe_get_parameter("tour_id")
        if request.method == 'POST':
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
        tour_id = safe_get_parameter("tour_id")

        if request.method == 'POST':

            agree = safe_get_parameter('agree')
            signature = safe_get_parameter('signature')
            if user_name == signature:

                if not agree:
                    flash("You must agree to the Code of Conduct before signing.", "danger")
                    return redirect(request.url)
                if not signature:
                    flash("Signature is required.", "danger")
                    return redirect(request.url)

                # Save Code of Conduct signature to database
                db.code_of_conducts.insert_one({
                    "user_id": str(current_user.id),
                    "signed_date": datetime.utcnow(),
                    "signature_text": signature,
                    "ip_address": request.remote_addr or socket.gethostbyname(socket.gethostname())
                })

                flash("Code of Conduct signed successfully.", "success")
                return redirect(url_for('tours.tour_checklist', tour_id=tour_id))
            else:
                flash("The signature and name must match. Please try again.", "danger")
        return render_template('code_of_conduct.html', user_name=user_name)
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))