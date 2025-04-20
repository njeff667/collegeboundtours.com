# utils/qa_loader.py
import os
import re
from dotenv import load_dotenv
from utils.security import handle_exception
from flask import redirect, url_for
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key = openai_api_key)

# Load Q&A data from text file into pairs
def load_knowledge_base(filepath):
    try:
        qa_pairs = []
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                entries = re.split(r"(?=Q:\s)", content)
                for entry in entries:
                    parts = entry.strip().split("A:", 1)
                    if len(parts) == 2:
                        question = parts[0].replace("Q:", "").strip()
                        answer = parts[1].strip()
                        qa_pairs.append((question, answer))
        return qa_pairs
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))

# Find the most relevant answer using TF-IDF
def get_relevant_answer(query, qa_pairs):
    try:
        if not qa_pairs:
            return "No data available."

        questions = [q for q, a in qa_pairs]
        vectorizer = TfidfVectorizer().fit_transform(questions + [query])
        similarities = cosine_similarity(vectorizer[-1], vectorizer[:-1]).flatten()
        best_match_index = similarities.argmax()

        # Return limited context
        question, answer = qa_pairs[best_match_index]
        return f"Q: {question}\nA: {answer}"
    except Exception as e:
        handle_exception(e)
        return redirect(url_for('home'))
