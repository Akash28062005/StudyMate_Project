from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey'

DB_NAME = "studymate.db"

# --- Initialize Database ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Drop tables if needed (optional during development)
    # c.execute("DROP TABLE IF EXISTS willingness")
    # c.execute("DROP TABLE IF EXISTS topics")
    # c.execute("DROP TABLE IF EXISTS users")

    # Create users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            profession TEXT NOT NULL,
            name TEXT NOT NULL
        )
    """)

    # Create topics table
    c.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            duration TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP,
            scheduled_datetime TEXT,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # Create willingness table to track users willing to join topics
    c.execute("""
        CREATE TABLE IF NOT EXISTS willingness (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            UNIQUE(user_id, topic_id)
        )
    """)

    conn.commit()
    conn.close()

# --- Routes ---

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('landing'))

    user = session['user']
    
    # Check if admin user
    if user.get('is_admin'):
        return redirect(url_for('admin_home'))
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get all topics with willingness count and scheduled date
    # topics structure: [id, title, description, duration, created_by, created_at, scheduled_datetime, username, name, willingness_count]
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.created_by, t.created_at,
               t.scheduled_datetime, u.username, u.name, COUNT(w.id) as willingness_count
        FROM topics t
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN willingness w ON t.id = w.topic_id
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """)
    raw_topics = c.fetchall()
    
    # Format created_at and scheduled_datetime to 12-hour format
    topics = []
    for topic in raw_topics:
        topic_list = list(topic)
        if topic_list[5]:  # created_at exists
            try:
                # Try different formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        dt = datetime.strptime(str(topic_list[5]), fmt)
                        topic_list[5] = dt.strftime('%b %d at %I:%M %p')
                        break
                    except ValueError:
                        continue
            except:
                topic_list[5] = str(topic_list[5])
        
        # Format scheduled_datetime
        if topic_list[6]:  # scheduled_datetime exists
            try:
                # Try different formats
                for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']:
                    try:
                        dt = datetime.strptime(str(topic_list[6]), fmt)
                        topic_list[6] = dt.strftime('%b %d, %Y at %I:%M %p')
                        break
                    except ValueError:
                        continue
            except:
                topic_list[6] = str(topic_list[6])
        
        topics.append(tuple(topic_list))
    
    # Get user's topics with willingness count
    # my_topics structure: [id, title, description, duration, created_by, created_at, scheduled_datetime, willingness_count]
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.created_by, t.created_at, t.scheduled_datetime, COUNT(w.id) as willingness_count
        FROM topics t
        LEFT JOIN willingness w ON t.id = w.topic_id
        WHERE t.created_by = ?
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """, (user['id'],))
    raw_my_topics = c.fetchall()
    
    # Format my_topics timestamps
    my_topics = []
    for topic in raw_my_topics:
        topic_list = list(topic)
        if topic_list[5]:  # created_at exists
            try:
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        dt = datetime.strptime(str(topic_list[5]), fmt)
                        topic_list[5] = dt.strftime('%b %d at %I:%M %p')
                        break
                    except ValueError:
                        continue
            except:
                topic_list[5] = str(topic_list[5])
        
        # Format scheduled_datetime
        if topic_list[6]:
            try:
                for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']:
                    try:
                        dt = datetime.strptime(str(topic_list[6]), fmt)
                        topic_list[6] = dt.strftime('%b %d, %Y at %I:%M %p')
                        break
                    except ValueError:
                        continue
            except:
                topic_list[6] = str(topic_list[6])
        
        my_topics.append(tuple(topic_list))
    
    # Get willingness counts for user
    c.execute("SELECT topic_id FROM willingness WHERE user_id = ?", (user['id'],))
    my_willingness = [row[0] for row in c.fetchall()]
    
    # Get list of willing users for each topic
    willing_users = {}
    for topic in my_topics:
        c.execute("""
            SELECT u.name, u.username
            FROM willingness w
            JOIN users u ON w.user_id = u.id
            WHERE w.topic_id = ?
        """, (topic[0],))
        willing_users[topic[0]] = [{'name': row[0], 'email': row[1]} for row in c.fetchall()]
    
    conn.close()

    return render_template('home.html', user=user, topics=topics, my_topics=my_topics, my_willingness=my_willingness, willing_users=willing_users)

@app.route('/admin_home')
def admin_home():
    if 'user' not in session or not session['user'].get('is_admin'):
        return redirect(url_for('landing'))
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get all users with their post count
    c.execute("""
        SELECT u.id, u.username, u.profession, u.name, COUNT(t.id) as post_count
        FROM users u
        LEFT JOIN topics t ON u.id = t.created_by
        GROUP BY u.id
        ORDER BY post_count DESC
    """)
    users = c.fetchall()
    
    conn.close()
    
    return render_template('admin_home.html', users=users)

@app.route('/admin_delete_user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if 'user' not in session or not session['user'].get('is_admin'):
        return redirect(url_for('landing'))
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Delete user's willingness entries
    c.execute("DELETE FROM willingness WHERE user_id = ?", (user_id,))
    # Delete user's topics and their willingness
    c.execute("SELECT id FROM topics WHERE created_by = ?", (user_id,))
    topic_ids = [row[0] for row in c.fetchall()]
    
    for topic_id in topic_ids:
        c.execute("DELETE FROM willingness WHERE topic_id = ?", (topic_id,))
    
    # Delete user's topics
    c.execute("DELETE FROM topics WHERE created_by = ?", (user_id,))
    # Delete user
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check for admin login
        if username == 'Admin' and password == 'Admin@123':
            session['user'] = {
                'is_admin': True,
                'username': 'Admin'
            }
            return redirect(url_for('admin_home'))

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['user'] = {
                'id': user[0],
                'username': user[1],
                'password': user[2],
                'profession': user[3],
                'name': user[4]
            }
            return redirect(url_for('home'))
        else:
            return "❌ Invalid username or password"

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        profession = request.form['profession']
        name = request.form['name']

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, profession, name) VALUES (?, ?, ?, ?)", (username, password, profession, name))
            conn.commit()
        except sqlite3.IntegrityError:
            return "⚠️ Username already exists"
        finally:
            conn.close()

        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/post_topic', methods=['POST'])
def post_topic():
    if 'user' not in session:
        return redirect(url_for('landing'))

    title = request.form['title']
    description = request.form['description']
    duration = request.form['duration']
    user_id = session['user']['id']
    
    # Get current local time
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO topics (title, description, duration, created_by, created_at) VALUES (?, ?, ?, ?, ?)", 
              (title, description, duration, user_id, current_time))
    conn.commit()
    conn.close()

    return redirect(url_for('home'))

@app.route('/schedule_session/<int:topic_id>', methods=['POST'])
def schedule_session(topic_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id = session['user']['id']
    scheduled_datetime = request.form['scheduled_datetime']

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Check if user owns the topic
    c.execute("SELECT created_by FROM topics WHERE id = ?", (topic_id,))
    topic = c.fetchone()
    
    if topic and topic[0] == user_id:
        c.execute("UPDATE topics SET scheduled_datetime = ? WHERE id = ?", (scheduled_datetime, topic_id))
        conn.commit()
        conn.close()
        return redirect(url_for('home'))
    
    conn.close()
    return jsonify({'error': 'Unauthorized'}), 403

@app.route('/delete_topic/<int:topic_id>', methods=['GET'])
def delete_topic(topic_id):
    if 'user' not in session:
        return redirect(url_for('landing'))

    user_id = session['user']['id']

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Check if user owns the topic
    c.execute("SELECT created_by FROM topics WHERE id = ?", (topic_id,))
    topic = c.fetchone()
    
    if topic and topic[0] == user_id:
        # Delete willingness entries first
        c.execute("DELETE FROM willingness WHERE topic_id = ?", (topic_id,))
        # Delete the topic
        c.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('home'))

@app.route('/willing_to_join/<int:topic_id>', methods=['POST'])
def willing_to_join(topic_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id = session['user']['id']

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    try:
        # Check if user owns the topic
        c.execute("SELECT created_by FROM topics WHERE id = ?", (topic_id,))
        topic = c.fetchone()
        
        if topic and topic[0] == user_id:
            return jsonify({'error': 'Cannot join your own topic'}), 403
        
        # Check if already willing
        c.execute("SELECT id FROM willingness WHERE user_id = ? AND topic_id = ?", (user_id, topic_id))
        existing = c.fetchone()
        
        if existing:
            # Remove willingness
            c.execute("DELETE FROM willingness WHERE user_id = ? AND topic_id = ?", (user_id, topic_id))
            action = 'removed'
        else:
            # Add willingness
            c.execute("INSERT INTO willingness (user_id, topic_id) VALUES (?, ?)", (user_id, topic_id))
            action = 'added'
        
        # Get updated count
        c.execute("SELECT COUNT(*) FROM willingness WHERE topic_id = ?", (topic_id,))
        count = c.fetchone()[0]
        
        conn.commit()
        conn.close()
        return jsonify({'action': action, 'count': count})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('landing'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
