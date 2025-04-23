# models/user.py
from flask_login import UserMixin
from datetime import datetime

class User(UserMixin):
    def __init__(self, user_doc):
        self.id = str(user_doc.get("_id"))
        self.email = user_doc.get("email")
        self.name = user_doc.get("name")
        self.role = user_doc.get("role", "student")
        self.password = user_doc.get("password")
        self.profile_complete = user_doc.get("profile_complete", False)
        self.profile = user_doc.get("profile", False)
        self.created_at = datetime.now()

    def get_id(self):
        return self.id

    def is_admin(self):
        return self.role == "admin"

    def is_driver(self):
        return self.role == "driver"

    def is_parent(self):
        return self.role == "parent"

    def is_student(self):
        return self.role == "student"