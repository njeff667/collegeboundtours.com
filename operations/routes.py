# operations/routes.py
from bson import ObjectId
from extensions import db  # assuming you initialized db in an extensions.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import db, mail, serializer
from utils.security import handle_exception, role_required, validate_file, allowed_file, upload_to_gcs
from werkzeug.utils import secure_filename
import os
import datetime

operations_bp = Blueprint("operations", __name__)
