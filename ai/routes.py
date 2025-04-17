# In ai/routes.py
from flask import Blueprint, request, jsonify, render_template
from utils.qa_loader import openai_client, load_knowledge_base, get_relevant_answer
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from bson import ObjectId

from extensions import db, mail, serializer
import os

ai_bp = Blueprint("ai", __name__)


# Limiter setup
limiter = Limiter(get_remote_address, app=None, default_limits=["30 per hour"])

# Attach limiter in app.py like: limiter.init_app(app)

# OpenAI client
response = openai_client.responses.create(
    model="gpt-4.1",
    input="Write a one-sentence bedtime story about a unicorn."
)


qa_file_path = os.path.join("static", "qa_data.txt")
knowledge_base = load_knowledge_base(qa_file_path)

@ai_bp.route("/ai/ask", methods=["POST"])
@limiter.limit("10 per minute")
def ask_bot():
    data = request.get_json()
    user_question = data.get("question", "").strip()

    if not user_question:
        return jsonify({"answer": "Please enter a question."}), 400

    relevant_context = get_relevant_answer(user_question, knowledge_base)
    prompt = f"Answer this question using ONLY the following text. If you don't know, say 'I'm not sure.':\n\n{relevant_context}\n\nQ: {user_question}\nA:"

    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = completion.choices[0].message.content.strip()

        if "I don't know" in answer or "I'm not sure" in answer:
            db.unanswered.insert_one({
                "question": user_question,
                "timestamp": datetime.utcnow()
            })

        return jsonify({"answer": answer})

    except Exception as e:
        return jsonify({"answer": "There was an error. Please try again later."}), 500

# Admin view of unanswered questions
@ai_bp.route("/admin/unanswered")
def view_unanswered():
    questions = list(db.unanswered.find().sort("timestamp", -1))
    return render_template("admin/unanswered.html", questions=questions)
