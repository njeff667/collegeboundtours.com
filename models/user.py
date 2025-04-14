# models/user.py
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, user_doc):
        self.id = str(user_doc.get("_id"))
        self.email = user_doc.get("email")
        self.name = user_doc.get("name")
        self.role = user_doc.get("role", "student")
        self.phone = user_doc.get("phone")
        self.profile_complete = user_doc.get("profile_complete", False)

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
