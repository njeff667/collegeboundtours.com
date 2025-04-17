# extensions.py
from flask_mail import Mail
from pymongo import MongoClient
from itsdangerous import URLSafeTimedSerializer
import os

mail = Mail()

serializer = URLSafeTimedSerializer(os.getenv("SECRET_KEY"))

# MongoDB setup
ENV = os.getenv("FLASK_ENV", "development")
MONGO_URI = os.getenv("MONGO_URI_PROD") if ENV == "production" else os.getenv("MONGO_URI_DEV")
client = MongoClient(MONGO_URI)
db = client["college_bound"]