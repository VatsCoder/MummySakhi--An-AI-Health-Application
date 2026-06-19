from flask import Flask, render_template,request,session,redirect
import sqlite3
from datetime import timedelta
import os
from google import genai
from google.genai import types
from google.genai.errors import ServerError
import time
import json
from dotenv import load_dotenv
from threading import Thread        
import pdfplumber                   
import pytesseract                  
from PIL import Image

load_dotenv()
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

ai_client = genai.Client()
DB_PATH = 'database.db'

# Function to connect to the database
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Returns rows as dictionaries
    return conn

# Initialize database
def init_db():
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        age INTEGER,
        height INTEGER,
        weight INTEGER,
        condn TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        sleep_hours REAL,
        workload_hours REAL,
        exercise_mins INTEGER,
        symptoms TEXT,
        log_date DATE DEFAULT CURRENT_DATE,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS medical_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_path TEXT,
            ai_analysis TEXT,
            upload_date DATE DEFAULT CURRENT_DATE,
            status TEXT DEFAULT 'processing',
            FOREIGN KEY (user_id) REFERENCES users(id)
    )""")
    
    # 2. Sub-table holding the individual incremental values
    conn.execute("""
        CREATE TABLE IF NOT EXISTS report_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            marker TEXT,
            value TEXT,
            reference TEXT,
            status TEXT,
            FOREIGN KEY (report_id) REFERENCES medical_reports(id)
    )""")
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT age, height, weight, condn 
        FROM profile 
        WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "age": row[0],
            "height": row[1],
            "weight": row[2],
            "conditions": row[3]
        }
    return {}


def extract_text_from_file(file_path):
    text = ""
    if file_path.lower().endswith(".pdf"):
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        # Fallback: scanned PDF — OCR each page
        if not text.strip():
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    img = page.to_image(resolution=200).original
                    text += pytesseract.image_to_string(img) + "\n"
    else:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img)
    return text.strip()


def _mark_failed(report_id):
    conn = sqlite3.connect('database.db')
    conn.execute(
        "UPDATE medical_reports SET status = 'failed' WHERE id = ?",
        (report_id,)
    )
    conn.commit()
    conn.close()

def process_report_in_background(report_id, user_id, file_path, report_text):
    """Runs all Gemini API calls in background — never blocks the user."""

    # ────────────────────────────────────────────────────────
    # STEP 1: BIOMARKER EXTRACTION
    # ────────────────────────────────────────────────────────
    biomarker_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "marker":    types.Schema(type=types.Type.STRING),
            "value":     types.Schema(type=types.Type.STRING),
            "reference": types.Schema(type=types.Type.STRING),
            "status":    types.Schema(type=types.Type.STRING)
        },
        required=["marker", "value", "reference", "status"]
    )

    max_retries = 5
    delay = 5
    response = None

    for attempt in range(max_retries):
        try:
            response = ai_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[f"Extract all health biomarkers from this report:\n\n{report_text[:4000]}"],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type=types.Type.ARRAY,
                        items=biomarker_schema
                    )
                )
            )
            break
        except ServerError as e:
            if e.code == 503 and attempt < max_retries - 1:
                print(f"Gemini busy. Retry {attempt+1}/{max_retries} in {delay}s...")
                time.sleep(delay)
                delay *= 3
            else:
                # Mark as failed in DB and exit
                _mark_failed(report_id)
                return
        except Exception as e:
            print(f"Extraction error: {e}")
            _mark_failed(report_id)
            return

    try:
        latest_metrics = json.loads(response.text)
    except Exception as e:
        print(f"JSON parse error: {e}")
        _mark_failed(report_id)
        return

    # ────────────────────────────────────────────────────────
    # STEP 2: SAVE BIOMARKERS TO DB
    # ────────────────────────────────────────────────────────
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    for item in latest_metrics:
        cursor.execute("""
            INSERT INTO report_values (report_id, marker, value, reference, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            report_id,
            item.get("marker", "Unknown"),
            item.get("value", "N/A"),
            item.get("reference", "N/A"),
            item.get("status", "Normal")
        ))
    conn.commit()
    time.sleep(15)

    # ────────────────────────────────────────────────────────
    # STEP 3: GATEKEEPER
    # ────────────────────────────────────────────────────────
    try:
        gatekeeper_response = ai_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=f"""Look at these markers: {json.dumps(latest_metrics)}
            Is historical comparison needed? Return JSON: {{"requires_history": true/false}}""",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        decision = json.loads(gatekeeper_response.text)
    except Exception:
        decision = {"requires_history": False}  # safe fallback

    historical_context = []
    if decision.get("requires_history"):
        cursor.execute("""
            SELECT rv.marker, rv.value, rv.status, mr.upload_date
            FROM report_values rv
            JOIN medical_reports mr ON rv.report_id = mr.id
            WHERE mr.user_id = ? AND mr.id < ?
            ORDER BY mr.upload_date DESC LIMIT 15
        """, (user_id, report_id))
        historical_context = [dict(row) for row in cursor.fetchall()]
    time.sleep(15)
    # ────────────────────────────────────────────────────────
    # STEP 4: FINAL INSIGHT GENERATION
    # ────────────────────────────────────────────────────────
    final_prompt = f"Analyze these markers:\n{json.dumps(latest_metrics)}\n\n"
    final_prompt += f"Historical data:\n{json.dumps(historical_context)}\n\n" if historical_context else "No historical data.\n\n"
    final_prompt += "Give 3 diagnostic action points relevant to maternal health."

    try:
        final_analysis = ai_client.models.generate_content(
            model='gemini-2.0-flash',
            contents=final_prompt
        )
        analysis_text = final_analysis.text
    except Exception as e:
        analysis_text = "Analysis could not be completed. Please re-upload the report."

    # ────────────────────────────────────────────────────────
    # STEP 5: MARK AS DONE IN DB
    # ────────────────────────────────────────────────────────
    cursor.execute("""
        UPDATE medical_reports 
        SET ai_analysis = ?, status = 'done'
        WHERE id = ?
    """, (analysis_text, report_id))

    conn.commit()
    conn.close()
    print(f"✅ Report {report_id} processed successfully.")

@app.route("/")
def main():
    if "user_id" in session:
        # Bypasses the welcome screen completely!
        return redirect("/dashboard")
    return render_template('index.html')

@app.route("/profile")
def profile():
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/")  # ✅ correct

    user = get_user(user_id) or {}

    return render_template("profile.html", user=user)

@app.route("/start")
def start():
    return render_template('get_started.html')

@app.route("/register", methods=["POST"])
def register():
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO users (name, email, password) VALUES (?, ?, ?)',
        (name, email, password)
    )

    user_id = cursor.lastrowid  # ✅ THIS IS IMPORTANT

    conn.commit()
    conn.close()

    session["user_id"] = user_id  # ✅ correct

    return redirect("/profile")
@app.route("/save-profile",methods=["POST"])
def save_profile():
    user_id = session.get("user_id")

    age = request.form['age']
    height = request.form['height']
    weight = request.form['weight']
    condn = request.form['conditions']

    conn = get_db_connection()
    cursor = conn.cursor()

    # check if profile exists
    cursor.execute("SELECT * FROM profile WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE profile 
            SET age=?, height=?, weight=?, condn=? 
            WHERE user_id=?
        """, (age, height, weight, condn, user_id))
    else:
        cursor.execute("""
            INSERT INTO profile (user_id, age, height, weight, condn)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, age, height, weight, condn))

    conn.commit()
    conn.close()
    return redirect("/dashboard")
@app.route("/dashboard")
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session.get("user_id")

    conn = get_db_connection()   
    cursor = conn.cursor()

    # ── FETCH PROFILE FROM DB ──────────────────────────────
    cursor.execute("""
        SELECT age, height, weight, condn 
        FROM profile WHERE user_id = ?
    """, (user_id,))
    profile_row = cursor.fetchone()

    user_data = {}
    if profile_row:
        user_data = {
            "age":        profile_row["age"],
            "height":     profile_row["height"],
            "weight":     profile_row["weight"],
            "conditions": profile_row["condn"]
        }

    # ────────────────────────────────────────────────────────
    # 1. YOUR EXISTING BMI CALCULATION LOGIC
    # ────────────────────────────────────────────────────────
    height_cm = user_data.get('height')
    weight_kg = user_data.get('weight')
    bmi_value = "N/A"
    bmi_status = "Unknown"

    if height_cm and weight_kg:
        try:
            h = float(height_cm)
            w = float(weight_kg)
            bmi_calculated = w / ((h / 100) ** 2)
            bmi_value = round(bmi_calculated, 1)
            print(bmi_value)
            if bmi_value < 18.5:
                bmi_status = "Underweight"
            elif 18.5 <= bmi_value < 25:
                bmi_status = "Healthy"
            elif 25 <= bmi_value < 30:
                bmi_status = "Overweight"
            else:
                bmi_status = "Obese"
        except ZeroDivisionError:
            pass

    # ────────────────────────────────────────────────────────
    # 2. YOUR EXISTING CURRENT WEEK SLEEP LOGIC
    # ────────────────────────────────────────────────────────
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT sleep_hours 
        FROM daily_logs 
        WHERE user_id = ? AND log_date >= date('now', '-7 days')
        ORDER BY log_date DESC
    """, (user_id,))
    rows = cursor.fetchall()
    
    total_sleep = 0
    log_count = len(rows)
    avg_sleep = 0.0
    sleep_status = "No Data"
    
    if log_count > 0:
        for row in rows:
            total_sleep += row["sleep_hours"]
        avg_sleep = round(total_sleep / log_count, 1)
        
        if avg_sleep >= 7.0:
            sleep_status = "Good"
        elif 6.0 <= avg_sleep < 7.0:
            sleep_status = "Fair"
        else:
            sleep_status = "Poor"

    # ────────────────────────────────────────────────────────
    # 3. YOUR EXISTING PREVIOUS WEEK COMPARISON LOGIC
    # ────────────────────────────────────────────────────────
    cursor.execute("""
        SELECT sleep_hours FROM daily_logs 
        WHERE user_id = ? AND log_date >= date('now', '-14 days') AND log_date < date('now', '-7 days')
    """, (user_id,))
    prev_rows = cursor.fetchall()
    
    prev_avg = 0.0
    if prev_rows:
        prev_avg = sum(r['sleep_hours'] for r in prev_rows) / len(prev_rows)
        
    comparison_text = "0% vs last week"
    change_direction = "neutral"
    
    if prev_avg > 0 and avg_sleep > 0:
        pct_change = round(((avg_sleep - prev_avg) / prev_avg) * 100, 0)
        if pct_change > 0:
            comparison_text = f"+{int(pct_change)}% vs last week"
            change_direction = "up"
        elif pct_change < 0:
            comparison_text = f"{int(pct_change)}% vs last week"
            change_direction = "down"
        else:
            comparison_text  = "0% vs last week"
    # ────────────────────────────────────────────────────────
    # 4. FIXED: FETCH LATEST REPORT AND READ DYNAMIC TEXT CELL
    # ────────────────────────────────────────────────────────
    # We added ai_analysis to our main select query block
    risk_level = "low"
    risk_status = "Stable"
    cursor.execute("""
        SELECT id, ai_analysis, upload_date, status FROM medical_reports 
        WHERE user_id = ? ORDER BY id DESC LIMIT 1
    """, (user_id,))
    latest_report = cursor.fetchone()
    
    metrics = []
    report_date = "No reports uploaded"
    # Safe default string if database returns blank
    ai_insights = "Upload a medical report inside the panel below to generate an automated clinical risk assessment summary."
    
    if latest_report:
        report_date = latest_report["upload_date"]
        report_status = latest_report["status"]

        if report_status == 'processing':
            ai_insights = "processing"
        elif report_status == 'failed':
            ai_insights = "failed"
        elif latest_report["ai_analysis"]:
            ai_insights = latest_report["ai_analysis"]

            cursor.execute("""
                SELECT marker, value, reference, status 
                FROM report_values 
                WHERE report_id = ?
            """, (latest_report["id"],))
            metrics = cursor.fetchall()
            abnormal = sum(1 for m in metrics if m["status"] in ("Low", "High"))
            if abnormal >= 3 or bmi_status == "Obese" or avg_sleep < 5:
                risk_level  = "High"
                risk_status = "Critical"
            elif abnormal >= 1 or bmi_status in ("Overweight", "Underweight") or avg_sleep < 6:
                risk_level  = "Medium"
                risk_status = "Monitor"

    conn.close()

    # ────────────────────────────────────────────────────────
    # 5. RETURNING CLEAN LOCAL PIPELINES STRAIGHT TO TEMPLATE
    # ────────────────────────────────────────────────────────
    return render_template(
        "dashboard.html", 
        user=user_data, 
        bmi=bmi_value, 
        status=bmi_status, 
        sleep_status=sleep_status,
        avg_sleep=avg_sleep,          
        comparison=comparison_text,   
        direction=change_direction,   
        report_date=report_date,       
        metrics=metrics,               
        ai_insights=ai_insights,
        risk_level    = risk_level,    
        risk_status   = risk_status      
    )
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/loging",methods=["GET","POST"])
def loging():
    if request.method == 'POST':
        email_input =  request.form.get('email')
        password_input= request.form.get('password')
        remember_ticked = request.form.get('remember_me')

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, password
            FROM users 
            WHERE email = ?
        """, (email_input,))

        user_row = cursor.fetchone()

        if user_row:
            db_id = user_row[0]
            db_password = user_row[1]

            if password_input == db_password:
                if remember_ticked:
                # Tells Flask to save this cookie file to the hard drive for 30 days
                    session.permanent = True
                    print("ticked")
                else:
                # Normal behavior: Cookie disappears when browser exits
                    session.permanent = False
                session['user_id'] = db_id 

                cursor.execute('SELECT age, height, weight, condn FROM profile WHERE user_id = ?', (db_id,))
                profile_row = cursor.fetchone()
                conn.close()

                if profile_row:
                    # profile_row[0]=age, profile_row[1]=height, profile_row[2]=weight, profile_row[3]=condn
                    session['user_details'] = {
                        "age": profile_row[0],
                        "height": profile_row[1],
                        "weight": profile_row[2],
                        "conditions": profile_row[3]
                    }
                else:
                    # If they have an account but haven't filled out their profile yet
                    session['user_details'] = {
                        "age": None, "height": None, "weight": None, "conditions": None
                    }

                # Safe redirect to your dashboard
                return redirect('/dashboard')
            else:
                conn.close()
                return "Incorrect password", 401
        else:
            conn.close()
            return "User not found", 404

    return render_template('login.html')

@app.route("/logout")
def logout():
    # 1. Wipe out all data (user_id and user_details) from the session cookie
    session.clear()
    
    # 2. Redirect the user back to the home page or login page
    return redirect("/")
@app.route("/save-daily-log", methods=["POST"])
def save_daily_log():

    user_id = session.get("user_id")
    if "user_id" not in session:
        return("/login")
    
    sleep = request.form.get("sleep")
    workload = request.form.get("workload")
    exercise = request.form.get("exercise")
    symptoms_list = request.form.getlist('symptoms')

    symptoms_string = ", ".join(symptoms_list) if symptoms_list else "None"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO daily_logs (user_id, sleep_hours, workload_hours, exercise_mins, symptoms)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, sleep, workload, exercise, symptoms_string))
    
    conn.commit()
    conn.close()

    # 5. Bring them back to the dashboard to refresh metrics view
    return redirect("/dashboard")

@app.route("/upload-report", methods=["POST"])
def upload_report():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")

    uploaded_file = request.files.get('medical_file')
    if not uploaded_file or uploaded_file.filename == '':
        return "No file selected.", 400

    os.makedirs('static/uploads', exist_ok=True)
    file_path = os.path.join('static/uploads', uploaded_file.filename)
    uploaded_file.save(file_path)

    # Extract text locally — fast, no API
    report_text = extract_text_from_file(file_path)
    if not report_text:
        return "Could not extract text. Please upload a clearer scan.", 400

    # Save report record immediately with status = 'processing'
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO medical_reports (user_id, file_path, status) VALUES (?, ?, 'processing')",
        (user_id, file_path)
    )
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Fire background thread — user doesn't wait for this
    thread = Thread(target=process_report_in_background,
                    args=(report_id, user_id, file_path, report_text))
    thread.daemon = True
    thread.start()

    # Redirect instantly ✅
    return redirect("/dashboard")