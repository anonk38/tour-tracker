from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tour_tracker_secret_key_2026")

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_bd_time(format_str="%d %b, %I:%M %p"):
    return (datetime.utcnow() + timedelta(hours=6)).strftime(format_str)

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    return conn

def init_db():
    if not DATABASE_URL: return
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                          (id SERIAL PRIMARY KEY, tour_name TEXT, admin_password TEXT, per_person_budget REAL DEFAULT 0, viewer_password TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS collections 
                          (id SERIAL PRIMARY KEY, member_name TEXT, amount REAL, date TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS expenses 
                          (id SERIAL PRIMARY KEY, category TEXT, title TEXT, amount REAL, date TEXT)''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS archived_tours 
                          (id SERIAL PRIMARY KEY, tour_name TEXT, start_date TEXT, total_collected REAL, total_expense REAL, balance REAL, per_person_budget REAL DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archived_expenses 
                          (id SERIAL PRIMARY KEY, tour_id INTEGER, category TEXT, title TEXT, amount REAL, date TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archived_collections 
                          (id SERIAL PRIMARY KEY, tour_id INTEGER, member_name TEXT, amount REAL, date TEXT)''')

        cursor.execute("SELECT * FROM settings WHERE id = 1")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO settings (id, tour_name, admin_password, per_person_budget, viewer_password) VALUES (1, %s, %s, %s, %s)", ("সিলেট ট্যুর ২০২৬", "1234", 0.0, "0000"))
            
        conn.commit()

init_db()

@app.route('/manifest.json')
def manifest():
    return {
        "name": "Tour Tracker",
        "short_name": "Tour Tracker",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#121212",
        "theme_color": "#121212",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/1086/1086741.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]
    }

def get_dashboard_data():
    with get_db_connection() as conn:
        c = conn.cursor()
        
        c.execute("SELECT tour_name, per_person_budget FROM settings WHERE id = 1")
        settings = c.fetchone()
        tour_name = settings['tour_name'] if settings else "New Tour"
        per_person_budget = settings['per_person_budget'] if settings and settings['per_person_budget'] else 0.0
        
        c.execute("SELECT SUM(amount) FROM collections")
        total_collected = c.fetchone()[0] or 0.0
        c.execute("SELECT SUM(amount) FROM expenses")
        total_expense = c.fetchone()[0] or 0.0
        balance = total_collected - total_expense
        
        c.execute("SELECT category, SUM(amount) FROM expenses GROUP BY category")
        breakdown = c.fetchall()
        c.execute("SELECT id, category, title, amount, date FROM expenses ORDER BY id DESC")
        expenses = c.fetchall()
        c.execute("SELECT member_name, SUM(amount) as total FROM collections GROUP BY member_name")
        members = c.fetchall()
        c.execute("SELECT id, member_name, amount, date FROM collections ORDER BY id DESC")
        collections_list = c.fetchall()
        c.execute("SELECT id, tour_name, start_date, total_collected, total_expense, balance FROM archived_tours ORDER BY id DESC")
        archived_tours = c.fetchall()
        
        members_count = len(members)
        actual_per_person_expense = (total_expense / members_count) if members_count > 0 else 0
        settlement_list = []
        for mem in members:
            paid = mem['total']
            diff = paid - actual_per_person_expense
            settlement_list.append({
                'name': mem['member_name'],
                'paid': paid,
                'diff': diff,
                'abs_diff': abs(diff)
            })
        
    return {
        "tour_name": tour_name,
        "per_person_budget": per_person_budget,
        "total_collected": total_collected,
        "total_expense": total_expense,
        "balance": balance,
        "breakdown": breakdown,
        "expenses": expenses,
        "members": members,
        "collections_list": collections_list,
        "archived_tours": archived_tours,
        "actual_per_person_expense": actual_per_person_expense,
        "settlement_list": settlement_list,
        "members_count": members_count
    }

@app.route('/')
def home():
    if not (session.get('is_viewer') or session.get('is_admin')):
        error = session.pop('login_error', None)
        return render_template('viewer_login.html', error=error)
        
    data = get_dashboard_data()
    is_admin = session.get('is_admin', False)
    error = session.pop('login_error', None)
    success = session.pop('success_msg', None)
    return render_template('index.html', **data, is_admin=is_admin, error=error, success=success)

@app.route('/viewer_login', methods=['POST'])
def viewer_login():
    pin = request.form.get('pin')
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT viewer_password, admin_password FROM settings WHERE id = 1")
        settings = c.fetchone()
        
    if settings and pin == settings['viewer_password']:
        session['is_viewer'] = True
    elif settings and pin == settings['admin_password']:
        session['is_viewer'] = True
        session['is_admin'] = True
    else:
        session['login_error'] = "ভুল পিন দিয়েছেন! / Invalid PIN!"
    return redirect(url_for('home'))

@app.route('/admin_login', methods=['POST'])
def admin_login():
    password = request.form.get('password')
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT admin_password FROM settings WHERE id = 1")
        db_pass = c.fetchone()
        
    if db_pass and password == db_pass['admin_password']:
        session['is_admin'] = True
        session['is_viewer'] = True
    else:
        session['login_error'] = "অ্যাডমিন পাসওয়ার্ড ভুল! / Wrong Admin PIN!"
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/update_tour_settings', methods=['POST'])
def update_tour_settings():
    if not session.get('is_admin'): return redirect(url_for('home'))
    name = request.form.get('tour_name')
    budget = float(request.form.get('per_person_budget') or 0)
    if name:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE settings SET tour_name = %s, per_person_budget = %s WHERE id = 1", (name, budget))
            conn.commit()
        session['success_msg'] = "ট্যুরের সেটিং আপডেট হয়েছে! / Settings Updated!"
    return redirect(url_for('home'))

@app.route('/update_passwords', methods=['POST'])
def update_passwords():
    if not session.get('is_admin'): return redirect(url_for('home'))
    v_pass = request.form.get('new_viewer_password')
    a_pass = request.form.get('new_admin_password')
    if v_pass and a_pass:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE settings SET viewer_password = %s, admin_password = %s WHERE id = 1", (v_pass, a_pass))
            conn.commit()
        session['success_msg'] = "পিন আপডেট সফল হয়েছে! / PIN Updated!"
    return redirect(url_for('home'))

@app.route('/archive_and_reset', methods=['POST'])
def archive_and_reset():
    if not session.get('is_admin'): return redirect(url_for('home'))
    new_tour_name = request.form.get('new_tour_name')
    if not new_tour_name: return redirect(url_for('home'))
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT tour_name, per_person_budget FROM settings WHERE id = 1")
        settings = c.fetchone()
        tour_name = settings['tour_name']
        per_person_budget = settings['per_person_budget'] or 0.0
        
        c.execute("SELECT SUM(amount) FROM collections")
        total_collected = c.fetchone()[0] or 0.0
        c.execute("SELECT SUM(amount) FROM expenses")
        total_expense = c.fetchone()[0] or 0.0
        balance = total_collected - total_expense
        start_date = get_bd_time("%d %b, %Y")
        
        c.execute("INSERT INTO archived_tours (tour_name, start_date, total_collected, total_expense, balance, per_person_budget) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                  (tour_name, start_date, total_collected, total_expense, balance, per_person_budget))
        archived_id = c.fetchone()[0]
        
        c.execute("INSERT INTO archived_expenses (tour_id, category, title, amount, date) SELECT %s, category, title, amount, date FROM expenses", (archived_id,))
        c.execute("INSERT INTO archived_collections (tour_id, member_name, amount, date) SELECT %s, member_name, amount, date FROM collections", (archived_id,))
        
        c.execute("DELETE FROM expenses")
        c.execute("DELETE FROM collections")
        c.execute("UPDATE settings SET tour_name = %s, per_person_budget = 0 WHERE id = 1", (new_tour_name,))
        conn.commit()
        
    session['success_msg'] = f"আগের ট্যুর আর্কাইভে সেভ হয়েছে! / Archived successfully!"
    return redirect(url_for('home'))

@app.route('/reset_current_tour', methods=['POST'])
def reset_current_tour():
    if not session.get('is_admin'): return redirect(url_for('home'))
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM expenses")
        c.execute("DELETE FROM collections")
        c.execute("UPDATE settings SET tour_name = 'New Tour', per_person_budget = 0 WHERE id = 1")
        conn.commit()
    session['success_msg'] = "বর্তমান ট্যুর সম্পূর্ণ মোছা হয়েছে! / Tour Reset Done!"
    return redirect(url_for('home'))

@app.route('/delete_archive/<int:tour_id>', methods=['POST'])
def delete_archive(tour_id):
    if not session.get('is_admin'): return redirect(url_for('home'))
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM archived_tours WHERE id = %s", (tour_id,))
        c.execute("DELETE FROM archived_expenses WHERE tour_id = %s", (tour_id,))
        c.execute("DELETE FROM archived_collections WHERE tour_id = %s", (tour_id,))
        conn.commit()
    session['success_msg'] = "ট্যুরটি চিরতরে মুছে ফেলা হয়েছে! / Deleted Permanently!"
    return redirect(url_for('home'))

@app.route('/restore_archive/<int:tour_id>', methods=['POST'])
def restore_archive(tour_id):
    if not session.get('is_admin'): return redirect(url_for('home'))
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT tour_name, per_person_budget FROM archived_tours WHERE id = %s", (tour_id,))
        arch_tour = c.fetchone()
        if arch_tour:
            c.execute("DELETE FROM expenses")
            c.execute("DELETE FROM collections")
            c.execute("UPDATE settings SET tour_name = %s, per_person_budget = %s WHERE id = 1", (arch_tour['tour_name'], arch_tour['per_person_budget']))
            c.execute("INSERT INTO expenses (category, title, amount, date) SELECT category, title, amount, date FROM archived_expenses WHERE tour_id = %s", (tour_id,))
            c.execute("INSERT INTO collections (member_name, amount, date) SELECT member_name, amount, date FROM archived_collections WHERE tour_id = %s", (tour_id,))
            c.execute("DELETE FROM archived_tours WHERE id = %s", (tour_id,))
            c.execute("DELETE FROM archived_expenses WHERE tour_id = %s", (tour_id,))
            c.execute("DELETE FROM archived_collections WHERE tour_id = %s", (tour_id,))
            conn.commit()
            session['success_msg'] = f"'{arch_tour['tour_name']}' পুনরায় সক্রিয় করা হয়েছে! / Tour Restored!"
    return redirect(url_for('home'))

@app.route('/view_archive/<int:tour_id>')
def view_archive(tour_id):
    if not (session.get('is_viewer') or session.get('is_admin')): return redirect(url_for('home'))
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM archived_tours WHERE id = %s", (tour_id,))
        tour_info = c.fetchone()
        c.execute("SELECT category, title, amount, date FROM archived_expenses WHERE tour_id = %s", (tour_id,))
        expenses = c.fetchall()
        c.execute("SELECT member_name, SUM(amount) as total FROM archived_collections WHERE tour_id = %s GROUP BY member_name", (tour_id,))
        members = c.fetchall()
        c.execute("SELECT category, SUM(amount) as total FROM archived_expenses WHERE tour_id = %s GROUP BY category", (tour_id,))
        breakdown = c.fetchall()
        
    return render_template('archive_detail.html', tour=tour_info, expenses=expenses, members=members, breakdown=breakdown)

@app.route('/add_collection', methods=['POST'])
def add_collection():
    if not session.get('is_admin'): return redirect(url_for('home'))
    member = request.form.get('member_name')
    raw_amount = request.form.get('amount')
    amount = float(raw_amount) if raw_amount and raw_amount.strip() != "" else 0.0
    date = get_bd_time()
    if member:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO collections (member_name, amount, date) VALUES (%s, %s, %s)", (member, amount, date))
            conn.commit()
    return redirect(url_for('home'))

@app.route('/edit_collection/<int:item_id>', methods=['POST'])
def edit_collection(item_id):
    if not session.get('is_admin'): return redirect(url_for('home'))
    member = request.form.get('member_name')
    raw_amount = request.form.get('amount')
    amount = float(raw_amount) if raw_amount and raw_amount.strip() != "" else 0.0
    if member:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE collections SET member_name = %s, amount = %s WHERE id = %s", (member, amount, item_id))
            conn.commit()
        session['success_msg'] = "আপডেট করা হয়েছে! / Updated!"
    return redirect(url_for('home'))

@app.route('/add_expense', methods=['POST'])
def add_expense():
    if not session.get('is_admin'): return redirect(url_for('home'))
    category = request.form.get('custom_category') if request.form.get('category') == 'custom' else request.form.get('category')
    title = request.form.get('title')
    amount = float(request.form.get('amount') or 0)
    date = get_bd_time()
    if category and amount > 0:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO expenses (category, title, amount, date) VALUES (%s, %s, %s, %s)", (category, title, amount, date))
            conn.commit()
    return redirect(url_for('home'))

@app.route('/edit_expense/<int:item_id>', methods=['POST'])
def edit_expense(item_id):
    if not session.get('is_admin'): return redirect(url_for('home'))
    category = request.form.get('category')
    title = request.form.get('title')
    amount = float(request.form.get('amount') or 0)
    if title and amount >= 0:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE expenses SET category = %s, title = %s, amount = %s WHERE id = %s", (category, title, amount, item_id))
            conn.commit()
        session['success_msg'] = "আপডেট করা হয়েছে! / Updated!"
    return redirect(url_for('home'))

@app.route('/delete_expense/<int:item_id>', methods=['POST'])
def delete_expense(item_id):
    if session.get('is_admin'):
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM expenses WHERE id = %s", (item_id,))
            conn.commit()
    return redirect(url_for('home'))

@app.route('/delete_collection/<int:item_id>', methods=['POST'])
def delete_collection(item_id):
    if session.get('is_admin'):
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM collections WHERE id = %s", (item_id,))
            conn.commit()
    return redirect(url_for('home'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)