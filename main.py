from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import nltk
import sqlite3
import hashlib
from datetime import datetime
import os
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()
NEWS_API_KEY = os.getenv('NEWS_API_KEY')

# Initialize Flask
app = Flask(__name__)
CORS(app)

# Simple NLTK setup - remove downloads for now
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('corpora/stopwords')
except LookupError:
    # Skip downloads for now to speed up build
    pass

# Database initialization
def init_db():
    conn = sqlite3.connect('/tmp/users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        subscription TEXT DEFAULT 'Free',
        usage_count INTEGER DEFAULT 5,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_reset DATE DEFAULT CURRENT_DATE
    )''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user(email):
    conn = sqlite3.connect('/tmp/users.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE email=?', (email,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(name, email, password):
    try:
        conn = sqlite3.connect('/tmp/users.db')
        c = conn.cursor()
        c.execute('INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
                  (name, email, hash_password(password)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False


class NewsVerifier:
    def __init__(self):
        pass

    def clean_text(self, text):
        return re.sub(r'[^\w\s]', '', text.lower())

    def get_news_articles(self, query):
        if not NEWS_API_KEY:
            # Fallback sample data for demo
            return [
                "Breaking news: Sample article about the query",
                "Latest updates on the topic from various sources",
                "Verified information from trusted news outlets"
            ]
        
        url = f"https://newsapi.org/v2/everything?q={query}&apiKey={NEWS_API_KEY}&language=en&pageSize=5"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                articles = [
                    f"{a.get('title','')} {a.get('description','')}".strip()
                    for a in data.get('articles', [])[:3]
                    if a.get('title')
                ]
                return articles if articles else ["No detailed articles found for this query"]
        except Exception as e:
            print(f"News API error: {e}")
        return ["Temporary data source unavailable - using demo mode"]

    def verify_statement(self, statement):
        articles = self.get_news_articles(statement)
        
        if not articles:
            return {
                'verification': 'Uncertain', 
                'confidence': 50.0,
                'statement': statement,
                'reason': 'Limited data available for verification. Please try with a more specific statement.',
                'sources': ['Data source temporarily unavailable']
            }
        
        # Simple text matching without scikit-learn
        article_text = ' '.join(articles).lower()
        statement_lower = statement.lower()
        
        # Basic keyword matching
        statement_words = [word for word in re.findall(r'\w+', statement_lower) if len(word) > 3]
        if not statement_words:
            statement_words = statement_lower.split()
            
        matching_words = [word for word in statement_words if word in article_text]
        match_ratio = len(matching_words) / len(statement_words) if statement_words else 0
        
        if match_ratio > 0.3:
            verdict, conf = 'Likely True', min(match_ratio * 100, 85)
        elif match_ratio > 0.1:
            verdict, conf = 'Uncertain', min(match_ratio * 80, 60)
        else:
            verdict, conf = 'Likely False', min((1 - match_ratio) * 70, 65)
                
        return {
            'verification': verdict, 
            'confidence': round(conf, 2),
            'statement': statement,
            'reason': f'Analysis of {len(articles)} articles shows {verdict.lower()} correlation with available sources. Based on basic text matching.',
            'sources': articles,
            'articles_analyzed': len(articles)
        }

# Initialize DB and verifier
init_db()
verifier = NewsVerifier()

# Routes
@app.route('/')
def home():
    return send_from_directory('.', 'home.html')

@app.route('/<path:path>')
def serve_static(path):
    if path.endswith('.html') or path == '':
        try:
            return send_from_directory('.', path)
        except:
            return send_from_directory('.', 'home.html')
    return send_from_directory('.', path)

@app.route('/verify', methods=['POST'])
def verify():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        claim = data.get('claim', '').strip()
        if not claim:
            return jsonify({'error': 'No claim provided'}), 400
            
        result = verifier.verify_statement(claim)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Verification failed: {str(e)}'}), 500

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
            
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if not all([name, email, password]):
            return jsonify({'success': False, 'message': 'All fields are required'})
            
        if create_user(name, email, password):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Email already exists'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Registration error: {str(e)}'})

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
            
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        user = get_user(email)
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})
            
        if hash_password(password) != user[3]:
            return jsonify({'success': False, 'message': 'Invalid password'})
            
        return jsonify({
            'success': True, 
            'user': {
                'email': user[2], 
                'subscription': user[4],
                'name': user[1],
                'usage_count': user[5]
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Login error: {str(e)}'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'message': 'Server is running on Vercel'})

# Vercel requires this
app = app

if __name__ == '__main__':
    app.run(debug=True)
