# utils/security.py
from cloudmersive_virus_api_client.rest import ApiException
from datetime import datetime
from extensions import db, mail, serializer
from functools import wraps
from flask import current_app, request, redirect, url_for, flash
from flask_login import current_user
from google.cloud import storage
from dotenv import load_dotenv
import cloudmersive_virus_api_client, os, time, traceback


# Load environment variables
load_dotenv()


# Pre-configure once when module loads
configuration = cloudmersive_virus_api_client.Configuration()
configuration.api_key['Apikey'] = os.getenv("CLOUDMERSIVE")

api_instance = cloudmersive_virus_api_client.ScanApi(cloudmersive_virus_api_client.ApiClient(configuration))


def handle_exception(e):
    """
    Handles an exception by saving to DB, logging, and printing stack trace if in development.
    """
    error_info = {
        "error_message": str(e),
        "stack_trace": traceback.format_exc(),
        "path": request.path if request else "N/A",
        "method": request.method if request else "N/A",
        "user_agent": request.headers.get('User-Agent') if request else "N/A",
        "remote_addr": request.remote_addr if request else "N/A",
        "timestamp": datetime.utcnow()
    }

    save_error_to_db(error_info)

    if os.getenv("FLASK_ENV") == "development":
        # Print full error to console for fast troubleshooting
        print("="*80)
        print("🚨 Exception Caught!")
        print(f"Error: {error_info['error_message']}")
        print(f"Path: {error_info['path']} Method: {error_info['method']}")
        print(f"User-Agent: {error_info['user_agent']}")
        print(f"Remote IP: {error_info['remote_addr']}")
        print("Full Stack Trace:")
        print(error_info["stack_trace"])
        print("="*80)
    else:
        # Production: just log to app's logger
        current_app.logger.error(f"Internal Server Error: {e}")

def save_error_to_db(error_info):
    """
    Save the structured error info to an external error_logs database.
    """
    db.error_logs.insert_one(error_info)

def sanitize_input(value):
    try:
        if not value:
            return "" if not isinstance(value, list) else []

        if isinstance(value, list):
            # Sanitize each item in the list recursively
            return [str(item).strip() for item in value if item is not None]

        # Handle single values
        return str(value).strip()

    except Exception as e:
        handle_exception(e)
        return "" if not isinstance(value, list) else []


def role_required(required_role):
    try:
        def decorator(view_func):
            @wraps(view_func)
            def wrapper(*args, **kwargs):
                if not current_user.is_authenticated:
                    flash("You must be logged in to access this page.", "warning")
                    return redirect(url_for("auth.login"))
                if getattr(current_user, "role", None) != required_role:
                    flash("You do not have permission to access this page.", "danger")
                    return redirect(url_for("home"))
                return view_func(*args, **kwargs)
            return wrapper
        return decorator
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

def allowed_file(filename):
    try:
        ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

def validate_file(file):
    try:
        if file and allowed_file(file.filename):
            return True
        return False
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

def upload_to_gcs(file, filename, bucket_name="your-gcs-bucket-name"):
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_file(file, content_type=file.content_type)
        blob.make_public()
        return blob.public_url
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
    
def scan_file_for_viruses(filepath):
    """
    Scan a file using Cloudmersive Virus Scan API.
    Pass the file path string. Return True if clean, False if infected or scan error.
    """
    try:
        result = api_instance.scan_file(filepath)  # PATH STRING, not file object!
        return result.clean_result
    except ApiException as e:
        print(f"🚨 Cloudmersive Virus Scan API Error: {e}")
        return False
    except Exception as general_e:
        print(f"🚨 General Error During Virus Scan: {general_e}")
        return False