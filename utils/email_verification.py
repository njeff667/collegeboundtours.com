# utils/email_verification.py
from flask_mail import Message
from flask import url_for, current_app
from extensions import db, mail, serializer
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

def get_serializer():
    return URLSafeTimedSerializer(current_app.secret_key)


def send_reset_email(recipient, token):
    reset_link = url_for('auth.reset_password', token=token, _external=True)
    subject = "Reset Your College Bound Tours Password"
    body = f"""
    Hi,

    To reset your password, click the link below:
    {reset_link}

    If you did not request this change, you can safely ignore this email.

    Thanks,
    College Bound Tours Team
    """
    msg = Message(subject, recipients=[recipient], body=body)
    mail.send(msg)


def send_email(subject, recipient, body):
    msg = Message(subject, recipients=[recipient], body=body)
    mail.send(msg)