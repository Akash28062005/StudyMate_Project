from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime

profile_bp = Blueprint('profile', __name__)

DB_NAME = "studymate.db"
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@profile_bp.route('/profile/<username>')
def view_profile(username):
    if 'user' not in session:
        return redirect(url_for('landing'))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get user details
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    user_data = c.fetchone()
    
    if not user_data:
        conn.close()
        return "User not found", 404
    
    user = {
        'id': user_data[0],
        'username': user_data[1],
        'profession': user_data[3],
        'name': user_data[4]
    }
    
    # Get user statistics
    stats = {}
    
    # Topics created
    c.execute("SELECT COUNT(*) FROM topics WHERE created_by = ?", (user['id'],))
    stats['topics_created'] = c.fetchone()[0]
    
    # Topics joined (through willingness)
    c.execute("SELECT COUNT(*) FROM willingness WHERE user_id = ?", (user['id'],))
    stats['topics_joined'] = c.fetchone()[0]
    
    # Average rating of their topics
    c.execute("""
        SELECT ROUND(AVG(r.rating), 2), COUNT(r.id)
        FROM topics t
        LEFT JOIN ratings r ON t.id = r.topic_id
        WHERE t.created_by = ?
    """, (user['id'],))
    avg_rating, total_ratings = c.fetchone()
    stats['avg_rating'] = avg_rating or 0.0
    stats['total_ratings'] = total_ratings or 0
    
    # Get recent activities
    activities = []
    
    # Topics created
    c.execute("""
        SELECT 'Created topic', title, created_at, id
        FROM topics
        WHERE created_by = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (user['id'],))
    for action, title, date, topic_id in c.fetchall():
        try:
            dt = datetime.strptime(str(date), '%Y-%m-%d %H:%M:%S')
            friendly_date = dt.strftime('%b %d, %Y at %I:%M %p')
        except:
            friendly_date = str(date)
            
        activities.append({
            'date': friendly_date,
            'title': action,
            'description': title
        })
    
    # Topics joined
    c.execute("""
        SELECT 'Joined topic', t.title, w.created_at, t.id
        FROM willingness w
        JOIN topics t ON w.topic_id = t.id
        WHERE w.user_id = ?
        ORDER BY w.created_at DESC
        LIMIT 5
    """, (user['id'],))
    for action, title, date, topic_id in c.fetchall():
        try:
            dt = datetime.strptime(str(date), '%Y-%m-%d %H:%M:%S')
            friendly_date = dt.strftime('%b %d, %Y at %I:%M %p')
        except:
            friendly_date = str(date)
            
        activities.append({
            'date': friendly_date,
            'title': action,
            'description': title
        })
    
    # Sort activities by date
    activities.sort(key=lambda x: datetime.strptime(x['date'], '%b %d, %Y at %I:%M %p'), reverse=True)
    activities = activities[:5]  # Keep only 5 most recent
    
    conn.close()
    
    # Check if this is the profile of the logged-in user
    is_own_profile = session['user']['username'] == username
    
    # Check for avatar
    avatar_path = os.path.join(UPLOAD_FOLDER, f"{username}.jpg")
    avatar_url = f"/static/avatars/{username}.jpg" if os.path.exists(avatar_path) else None
    
    return render_template('profile.html',
                         user=user,
                         stats=stats,
                         activities=activities,
                         is_own_profile=is_own_profile,
                         avatar_url=avatar_url)

@profile_bp.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user' not in session:
        return redirect(url_for('landing'))
    
    user_id = session['user']['id']
    name = request.form.get('name')
    profession = request.form.get('profession')
    
    if not name or not profession:
        flash("Name and profession are required", "error")
        return redirect(url_for('profile.view_profile', username=session['user']['username']))
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Update user details
    c.execute("UPDATE users SET name = ?, profession = ? WHERE id = ?",
              (name, profession, user_id))
    
    # Handle avatar upload
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename and allowed_file(file.filename):
            # Save with username as filename
            filename = f"{session['user']['username']}.jpg"
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
    
    conn.commit()
    conn.close()
    
    # Update session data
    session['user']['name'] = name
    session['user']['profession'] = profession
    
    flash("Profile updated successfully!", "success")
    return redirect(url_for('profile.view_profile', username=session['user']['username']))

# Change route to '/<username>' so url_for('profile.profile', username=...) works
@profile_bp.route('/<username>')
def profile(username):
    return view_profile(username)