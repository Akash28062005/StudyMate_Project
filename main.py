from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey'

from routes.profile import profile_bp
app.register_blueprint(profile_bp)

DB_NAME = "studymate.db"
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

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

    # Ensure optional category column exists on topics
    try:
        c.execute("PRAGMA table_info(topics)")
        cols = [row[1] for row in c.fetchall()]
        if 'category' not in cols:
            c.execute("ALTER TABLE topics ADD COLUMN category TEXT")
    except Exception:
        pass

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

    # Create ratings table (0..5, 0.5 steps allowed)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            rating REAL NOT NULL CHECK (rating >= 0 AND rating <= 5),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            UNIQUE(user_id, topic_id)
        )
    """)

    # Ensure feedback column exists on ratings
    try:
        c.execute("PRAGMA table_info(ratings)")
        rcols = [row[1] for row in c.fetchall()]
        if 'feedback' not in rcols:
            c.execute("ALTER TABLE ratings ADD COLUMN feedback TEXT")
    except Exception:
        pass


    # Create messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            topic_id INTEGER,
            subject TEXT,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
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
    
    # Get all topics with willingness, rating aggregates and scheduled date
    # topics structure: [id, title, description, duration, created_by, created_at, scheduled_datetime, username, name, willingness_count, category, avg_rating, ratings_count]
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.created_by, t.created_at,
               t.scheduled_datetime, u.username, u.name,
               COUNT(DISTINCT w.id) as willingness_count,
               IFNULL(t.category, ''),
               ROUND(AVG(r.rating), 2) as avg_rating,
               COUNT(r.id) as ratings_count
        FROM topics t
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN willingness w ON t.id = w.topic_id
        LEFT JOIN ratings r ON t.id = r.topic_id
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """)
    raw_topics = c.fetchall()
    
    # Format created_at and scheduled_datetime to 12-hour format
    topics = []
    now = datetime.now()
    for topic in raw_topics:
        topic_list = list(topic)
        original_scheduled = topic_list[6]  # Keep original for date check
        
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
        
        # Format scheduled_datetime and check if date has passed
        can_feedback = True  # Default: can give feedback if no scheduled date
        if topic_list[6]:  # scheduled_datetime exists
            try:
                # Try different formats
                for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']:
                    try:
                        dt = datetime.strptime(str(topic_list[6]), fmt)
                        topic_list[6] = dt.strftime('%b %d, %Y at %I:%M %p')
                        # Check if scheduled date has passed
                        can_feedback = now >= dt
                        break
                    except ValueError:
                        continue
            except:
                topic_list[6] = str(topic_list[6])
        
        # Normalize rating fields (avg may be None)
        if topic_list[11] is None:
            topic_list[11] = 0.0
        
        # Add can_feedback flag (append to topic_list)
        topic_list.append(can_feedback)
        topics.append(tuple(topic_list))
    
    # Get user's topics with willingness count and ratings
    # my_topics structure: [id, title, description, duration, created_by, created_at, scheduled_datetime, willingness_count, category, avg_rating, ratings_count]
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.created_by, t.created_at, t.scheduled_datetime,
               COUNT(DISTINCT w.id) as willingness_count,
               IFNULL(t.category, ''),
               ROUND(AVG(r.rating), 2) as avg_rating,
               COUNT(r.id) as ratings_count
        FROM topics t
        LEFT JOIN willingness w ON t.id = w.topic_id
        LEFT JOIN ratings r ON t.id = r.topic_id
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
        
        # Normalize rating fields
        if topic_list[9] is None:
            topic_list[9] = 0.0
        my_topics.append(tuple(topic_list))
    
    # Get willingness counts for user
    c.execute("SELECT topic_id FROM willingness WHERE user_id = ?", (user['id'],))
    my_willingness = [row[0] for row in c.fetchall()]
    
    # Get list of willing users for each topic
    willing_users = {}
    # Get list of ratings + feedback for each topic
    topic_ratings = {}
    for topic in my_topics:
        # Willing users
        c.execute("""
            SELECT u.name, u.username
            FROM willingness w
            JOIN users u ON w.user_id = u.id
            WHERE w.topic_id = ?
        """, (topic[0],))
        willing_users[topic[0]] = [{'name': row[0], 'email': row[1]} for row in c.fetchall()]

        # Ratings and feedback
        c.execute("""
            SELECT u.name, r.rating, IFNULL(r.feedback, ''), r.created_at
            FROM ratings r
            JOIN users u ON r.user_id = u.id
            WHERE r.topic_id = ?
            ORDER BY r.created_at DESC
        """, (topic[0],))
        rows = c.fetchall()
        # Format created_at to readable 12-hour time
        formatted = []
        for name, rating, feedback, created_at in rows:
            ts = str(created_at) if created_at is not None else ''
            try:
                dt = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.strptime(ts, fmt)
                        break
                    except ValueError:
                        continue
                created_str = dt.strftime('%b %d at %I:%M %p') if dt else ts
            except Exception:
                created_str = ts
            formatted.append({'name': name, 'rating': rating, 'feedback': feedback, 'when': created_str})
        topic_ratings[topic[0]] = formatted
    
    # Get user's joined classes (topics where user is willing)
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.created_by, t.created_at, t.scheduled_datetime,
               COUNT(DISTINCT w.id) as willingness_count,
               u.name,
               IFNULL(t.category, ''),
               ROUND(AVG(r.rating), 2) as avg_rating,
               COUNT(r.id) as ratings_count
        FROM topics t
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN willingness w ON t.id = w.topic_id
        LEFT JOIN ratings r ON t.id = r.topic_id
        WHERE t.id IN (
            SELECT topic_id FROM willingness WHERE user_id = ?
        )
        GROUP BY t.id
        ORDER BY t.created_at DESC
    """, (user['id'],))
    raw_joined_topics = c.fetchall()
    
    # Format joined_topics timestamps
    joined_topics = []
    for topic in raw_joined_topics:
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
        
        # Normalize rating fields
        if topic_list[10] is None:
            topic_list[10] = 0.0
        joined_topics.append(tuple(topic_list))
    
    # Get ratings for joined topics
    joined_topic_ratings = {}
    for topic in joined_topics:
        c.execute("""
            SELECT u.name, r.rating, IFNULL(r.feedback, ''), r.created_at
            FROM ratings r
            JOIN users u ON r.user_id = u.id
            WHERE r.topic_id = ?
            ORDER BY r.created_at DESC
        """, (topic[0],))
        rows = c.fetchall()
        formatted = []
        for name, rating, feedback, created_at in rows:
            ts = str(created_at) if created_at is not None else ''
            try:
                dt = None
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.strptime(ts, fmt)
                        break
                    except ValueError:
                        continue
                created_str = dt.strftime('%b %d at %I:%M %p') if dt else ts
            except Exception:
                created_str = ts
            formatted.append({'name': name, 'rating': rating, 'feedback': feedback, 'when': created_str})
        joined_topic_ratings[topic[0]] = formatted
    # Map of user ratings for quick lookup
    c = None
    conn.close()

    return render_template('home.html',
                           user=user,
                           topics=topics,
                           my_topics=my_topics,
                           my_willingness=my_willingness,
                           willing_users=willing_users,
                           topic_ratings=topic_ratings,
                           joined_topics=joined_topics,
                           joined_topic_ratings=joined_topic_ratings)

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
    category = request.form.get('category', '').strip()
    user_id = session['user']['id']
    
    # Get current local time
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO topics (title, description, duration, created_by, created_at, category) VALUES (?, ?, ?, ?, ?, ?)", 
              (title, description, duration, user_id, current_time, category))
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


@app.route('/rate_topic/<int:topic_id>', methods=['POST'])
def rate_topic(topic_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id = session['user']['id']
    try:
        rating = float(request.form.get('rating', '0'))
    except ValueError:
        return jsonify({'error': 'Invalid rating'}), 400

    if rating < 0 or rating > 5:
        return jsonify({'error': 'Rating out of range'}), 400

    feedback = request.form.get('feedback', '').strip()
    
    # Get current local time with seconds for precise timestamping
    now = datetime.now()
    current_time = now.strftime('%Y-%m-%d %H:%M:%S')
    friendly_time = now.strftime('%b %d, %Y at %I:%M:%S %p')  # More readable format

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Check if topic has a scheduled date and if it has passed
    c.execute("SELECT scheduled_datetime FROM topics WHERE id = ?", (topic_id,))
    topic = c.fetchone()
    
    if topic and topic[0]:
        # Topic has a scheduled date, check if it has passed
        try:
            # Try different formats for scheduled_datetime
            scheduled_str = str(topic[0])
            scheduled_dt = None
            for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                try:
                    scheduled_dt = datetime.strptime(scheduled_str, fmt)
                    break
                except ValueError:
                    continue
            
            if scheduled_dt:
                now = datetime.now()
                if now < scheduled_dt:
                    conn.close()
                    return jsonify({'error': 'Feedback can only be submitted after the scheduled session date'}), 400
        except Exception:
            # If parsing fails, allow rating (backward compatibility)
            pass
    
    try:
        # Check if rating already exists
        c.execute("SELECT id FROM ratings WHERE user_id = ? AND topic_id = ?", (user_id, topic_id))
        existing = c.fetchone()
        
        if existing:
            # Update existing rating
            if feedback:
                c.execute("UPDATE ratings SET rating = ?, feedback = ?, updated_at = ? WHERE user_id = ? AND topic_id = ?",
                          (rating, feedback, current_time, user_id, topic_id))
            else:
                c.execute("UPDATE ratings SET rating = ?, updated_at = ? WHERE user_id = ? AND topic_id = ?",
                          (rating, current_time, user_id, topic_id))
        else:
            # Insert new rating with current local time
            c.execute("INSERT INTO ratings (user_id, topic_id, rating, feedback, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                      (user_id, topic_id, rating, feedback, current_time, current_time))
        
        # Return fresh aggregates
        c.execute("SELECT ROUND(AVG(rating), 2), COUNT(1) FROM ratings WHERE topic_id = ?", (topic_id,))
        avg_rating, count = c.fetchone()
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'avg': avg_rating or 0.0, 'count': count})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500

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


@app.route('/calendar')
def calendar_view():
    if 'user' not in session:
        return redirect(url_for('landing'))
    
    user_id = session['user']['id']
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get all scheduled topics organized by date/time
    c.execute("""
        SELECT t.id, t.title, t.description, t.duration, t.scheduled_datetime, 
               u.name, IFNULL(t.category, ''),
               COUNT(DISTINCT w.id) as member_count
        FROM topics t
        LEFT JOIN users u ON t.created_by = u.id
        LEFT JOIN willingness w ON t.id = w.topic_id
        WHERE t.scheduled_datetime IS NOT NULL 
        GROUP BY t.id
        ORDER BY t.scheduled_datetime ASC
    """)
    topics_raw = c.fetchall()
    
    # Get user's opted-in topics
    c.execute("SELECT topic_id FROM willingness WHERE user_id = ?", (user_id,))
    user_opted = [row[0] for row in c.fetchall()]
    
    # Format calendar data
    import json
    calendar_data = []
    for topic in topics_raw:
        if topic[4]:  # scheduled_datetime exists
            # Format the datetime
            scheduled_dt = str(topic[4])
            try:
                for fmt in ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        dt = datetime.strptime(scheduled_dt, fmt)
                        formatted_dt = dt.strftime('%Y-%m-%d %H:%M')
                        break
                    except ValueError:
                        continue
                else:
                    formatted_dt = scheduled_dt
            except:
                formatted_dt = scheduled_dt
            
            calendar_data.append({
                'id': topic[0],
                'title': topic[1],
                'description': topic[2],
                'duration': topic[3],
                'scheduled_datetime': formatted_dt,
                'instructor': topic[5] or 'Unknown',
                'category': topic[6] if topic[6] else None,
                'members': topic[7]
            })
    
    # Convert to JSON
    calendar_data_json = json.dumps(calendar_data, default=str)
    user_opted_json = json.dumps(user_opted)
    
    conn.close()
    
    return render_template('calendar_new.html', 
                         calendar_data=calendar_data_json,
                         user_opted=user_opted_json)

@app.route('/messages')
def messages_view():
    if 'user' not in session:
        return redirect(url_for('landing'))
    
    user_id = session['user']['id']
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get unique conversation partners and last message
    c.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN sender_id = ? THEN receiver_id 
                ELSE sender_id 
            END as other_user_id,
            MAX(created_at) as last_msg_time
        FROM messages
        WHERE sender_id = ? OR receiver_id = ?
        GROUP BY other_user_id
        ORDER BY last_msg_time DESC
    """, (user_id, user_id, user_id))
    
    conversations = []
    for row in c.fetchall():
        other_user_id = row[0]
        c.execute("SELECT username, name FROM users WHERE id = ?", (other_user_id,))
        user_info = c.fetchone()
        if user_info:
            conversations.append({
                'user_id': other_user_id,
                'username': user_info[0],
                'name': user_info[1]
            })
    
    conn.close()
    return render_template('messages.html', conversations=conversations)

@app.route('/messages/load/<int:other_user_id>', methods=['GET'])
def load_messages(other_user_id):
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    user_id = session['user']['id']
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get all messages between these two users
    c.execute("""
        SELECT id, sender_id, message, created_at 
        FROM messages
        WHERE (sender_id = ? AND receiver_id = ?) 
           OR (sender_id = ? AND receiver_id = ?)
        ORDER BY created_at ASC
    """, (user_id, other_user_id, other_user_id, user_id))
    
    messages = []
    for row in c.fetchall():
        messages.append({
            'id': row[0],
            'sender_id': row[1],
            'text': row[2],
            'sent_at': row[3]
        })
    
    # Mark messages as read
    c.execute("""
        UPDATE messages 
        SET is_read = 1 
        WHERE receiver_id = ? AND sender_id = ? AND is_read = 0
    """, (user_id, other_user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'messages': messages})

@app.route('/messages/send', methods=['POST'])
def send_message():
    if 'user' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    user_id = session['user']['id']
    data = request.json
    recipient_id = data.get('recipient_id')
    message_text = data.get('message')
    
    if not recipient_id or not message_text:
        return jsonify({'error': 'Missing fields'}), 400
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    try:
        c.execute("""
            INSERT INTO messages (sender_id, receiver_id, message)
            VALUES (?, ?, ?)
        """, (user_id, recipient_id, message_text))
        
        conn.commit()
        msg_id = c.lastrowid
        conn.close()
        
        return jsonify({'ok': True, 'id': msg_id})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500




if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)