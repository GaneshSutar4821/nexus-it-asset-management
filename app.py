import qrcode
import base64
from datetime import datetime
import os
from io import BytesIO
from functools import wraps
import shutil
import threading

from flask import Flask, render_template, request, redirect, send_file, url_for, abort, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import google.generativeai as genai

from sqlalchemy import or_  # Imported safely for advanced database filtering

from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
app.secret_key = "it_asset_system_secure_key_2026"

# --- RELATIONAL SQL ENGINE CONFIGURATION ---
# Grab the cloud database URL from Render, or use local SQLite if it fails
db_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')

# Fix Render's URL format for SQLAlchemy
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
from flask_mail import Mail, Message

# --- EMAIL ENGINE CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

# --- AI TRIAGE ENGINE CONFIGURATION ---
gemini_api_key = os.environ.get('GEMINI_API_KEY')
genai.configure(api_key=gemini_api_key)

# AUTO-CLEAN VALUES TO REMOVE GHOST SPACES OR HIDDEN SYMBOLS
raw_user = os.environ.get('SYSTEM_EMAIL_USER', '')
raw_pass = os.environ.get('SYSTEM_EMAIL_PASS', '')

app.config['MAIL_USERNAME'] = raw_user.strip()
app.config['MAIL_PASSWORD'] = raw_pass.strip().replace(" ", "")
app.config['MAIL_DEFAULT_SENDER'] = ('Nexus IT System', app.config['MAIL_USERNAME'])

mail = Mail(app)

# --- CONFIGURING THE ENCRYPTION INTEGRATIONS ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ==========================================
# 1. ORM DATABASE MODELS
# ==========================================

class UserModel(db.Model, UserMixin):
    __tablename__ = 'users'
    username = db.Column(db.String(100), primary_key=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)

    def get_id(self):
        return self.username

class AssetModel(db.Model):
    __tablename__ = 'assets'
    asset_id = db.Column(db.String(100), primary_key=True)
    asset_type = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    
    # Linked to the users table via foreign key constraints
    user = db.Column(db.String(100), db.ForeignKey('users.username', ondelete='SET NULL'))
    
    department = db.Column(db.String(100))
    status = db.Column(db.String(50))
    warranty_period = db.Column(db.String(50))
    serial_no = db.Column(db.String(100))
    tag_id = db.Column(db.String(100))
    warranty_expiry = db.Column(db.String(50))
    grn_no = db.Column(db.String(100))
    grn_date = db.Column(db.String(50))
    supplier_name = db.Column(db.String(100))
    supplier_invoice_no = db.Column(db.String(100))
    supplier_invoice_date = db.Column(db.String(50))
    record_status = db.Column(db.String(20), default='Active')
    deleted_date = db.Column(db.String(50))
    updated_date = db.Column(db.String(50))

class AssignmentModel(db.Model):
    __tablename__ = 'assignments'
    assignment_id = db.Column(db.String(100), primary_key=True)
    asset_id = db.Column(db.String(100), nullable=False)
    employee_name = db.Column(db.String(100))
    department = db.Column(db.String(100))
    assigned_date = db.Column(db.String(50))
    return_date = db.Column(db.String(50))
    status = db.Column(db.String(50))

class TicketModel(db.Model):
    __tablename__ = 'tickets'
    ticket_id = db.Column(db.String(100), primary_key=True)
    asset_id = db.Column(db.String(100), nullable=False)
    issue = db.Column(db.String(255))
    raised_by = db.Column(db.String(100))
    priority = db.Column(db.String(50))
    status = db.Column(db.String(50))
    description = db.Column(db.Text)
    created_date = db.Column(db.String(50))
    closed_date = db.Column(db.String(50))
    assigned_to = db.Column(db.String(100))
    department = db.Column(db.String(100))
    notes = db.Column(db.Text)
    last_updated = db.Column(db.String(50))

class TransactionModel(db.Model):
    __tablename__ = 'transactions'
    transaction_id = db.Column(db.String(100), primary_key=True)
    asset_id = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(100))
    date = db.Column(db.String(50))
    remarks = db.Column(db.String(255))

class RequestModel(db.Model):
    __tablename__ = 'requests'
    request_id = db.Column(db.String(100), primary_key=True)
    requested_by = db.Column(db.String(100), nullable=False)
    asset_type = db.Column(db.String(100), nullable=False)
    purpose = db.Column(db.String(255))
    date_submitted = db.Column(db.String(50))
    status = db.Column(db.String(50), default='Pending')

class AuditLogModel(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100))
    action = db.Column(db.String(255))
    asset_id = db.Column(db.String(100))
    timestamp = db.Column(db.String(50))

@login_manager.user_loader
def load_user(username):
    return UserModel.query.get(str(username))

# --- ROLE-BASED ACCESS CONTROL DECORATOR ---
def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or getattr(current_user, 'role', None) not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def add_transaction(asset_id, action, remarks=""):
    total_trans = TransactionModel.query.count()
    transaction_id = f"TRN{total_trans + 1:04d}"
    new_log = TransactionModel(
        transaction_id=transaction_id,
        asset_id=str(asset_id),
        action=action,
        date=datetime.now().strftime("%d/%m/%Y"),
        remarks=remarks
    )
    db.session.add(new_log)
    db.session.commit()

def log_audit(action, asset_id):
    new_log = AuditLogModel(
        username=current_user.username,
        action=action,
        asset_id=asset_id,
        timestamp=datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    )
    db.session.add(new_log)
    db.session.commit()
    
from flask import current_app

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            print(f"📧 Background notification sent successfully to {msg.recipients}")
        except Exception as e:
            print(f"⚠️ Email engine background failure: {str(e)}")

def send_system_email(subject, recipient, body_html):
    """Queues and triggers a system notification email in a background thread."""
    app = current_app._get_current_object()
    
    msg = Message(
        subject=subject,
        recipients=[recipient]
    )
    msg.html = body_html
    
    # Start the email processing on a separate parallel thread
    thr = threading.Thread(target=send_async_email, args=[app, msg])
    thr.start()
    print(f"🚀 Email queued in background thread for {recipient}")

def ai_analyze_ticket(issue_summary, fault_description):
    """Sends the ticket text to the AI to get a categorized assessment."""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        You are an expert IT Support Assistant. Review this incoming support ticket:
        Issue: {issue_summary}
        Description: {fault_description}
        
        Please provide:
        1. The likely Category (Hardware, Software, Network, or Database).
        2. One short, immediate troubleshooting step the admin should take.
        Keep the response brief and professional.
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"AI Engine offline: {e}")
        return "AI Triage currently unavailable."
    
def send_discord_webhook(message_content):
    """Sends an instant real-time notification alert to the IT Discord server channel."""
    webhook_url = "https://discord.com/api/webhooks/1522555526146293770/swVHrVhkrTue9nXL353jOdkoUdhIbhgLfQtzZ1CY9d8Gbvm-Ert6kyFETQP-BdPJOrK9"
    payload = {"content": message_content}
    try:
        import requests
        requests.post(webhook_url, json=payload, timeout=5)
        print("🚀 Discord webhook alert transmitted successfully!")
    except Exception as e:
        print(f"⚠️ Webhook integration failure: {str(e)}")

# Login Page
@app.route("/", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        next_page = request.args.get("next") or request.form.get("next")
        return redirect(next_page if next_page else "/portal")
        
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = UserModel.query.get(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            
            # Check if a specific tracking target destination exists
            next_page = request.args.get("next") or request.form.get("next")
            if next_page:
                return redirect(next_page)
            
            return redirect("/portal")
            
        error = "Invalid username or password. please try again."

    return render_template("login.html", error=error)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/portal")
@login_required
def portal():
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template("portal.html", role=current_user.role, alert_count=alert_count)

# Asset Page
@app.route("/assets")
@login_required
def assets():
    # 1. Base query: Start with assets belonging only to the current user
    query = AssetModel.query.filter(
        or_(
            AssetModel.record_status != "DEL",
            AssetModel.record_status == None,
            AssetModel.record_status == ""
        )
    )
    
    # 2. Apply search filters (on top of the user's personal assets)
    search = request.args.get("search", "").strip()
    search_by = request.args.get("search_by", "").strip()

    if search and search_by:
        if search_by == "Assets Id":
            query = query.filter(AssetModel.asset_id == search)
        elif search_by == "Type":
            query = query.filter(AssetModel.asset_type.contains(search))
        elif search_by == "Brand":
            query = query.filter(AssetModel.brand.contains(search))
        elif search_by == "Model":
            query = query.filter(AssetModel.model.contains(search))
        elif search_by == "Department":
            query = query.filter(AssetModel.department.contains(search))
        elif search_by == "Status":
            query = query.filter(AssetModel.status == search)

    # 3. Get the final list of assets to display
    all_assets = query.all()
    
    # 4. Calculate Global Dashboard Metrics 
    total_assets = AssetModel.query.count()
    active_assets = AssetModel.query.filter_by(status='Active').count()
    inactive_assets = AssetModel.query.filter_by(status='Inactive').count()

    dept_data = {}
    for a in all_assets:
        if a.department:
            dept_data[a.department] = dept_data.get(a.department, 0) + 1

    assets_list = []
    expiring_assets_list = []
    today = datetime.today()
    selected_asset = None

    # 5. Process data for the table and QR generation
    for a in all_assets:
        row = {
            "Assets Id": a.asset_id, "Type": a.asset_type, "Brand": a.brand, "Model": a.model,
            "User": a.user if a.user else "-", "Department": a.department, "Status": a.status, "GRN No.": a.grn_no,
            "GRN Date": a.grn_date, "Supplier Name": a.supplier_name, "Supplier Invoice No.": a.supplier_invoice_no,
            "Supplier Invoice Date": a.supplier_invoice_date, "Serial No": a.serial_no, "TAG Id": a.tag_id,
            "Warranty Period": a.warranty_period, "Warranty Expiry": a.warranty_expiry
        }
        assets_list.append(row)

        if search and search_by == "Assets Id" and str(a.asset_id) == str(search):
            selected_asset = row

        if a.warranty_expiry:
            try:
                clean_date = str(a.warranty_expiry).strip()
                expiry_dt = datetime.strptime(clean_date, "%d/%m/%Y")
                if (expiry_dt - today).days <= 30:
                    expiring_assets_list.append(row)
            except Exception:
                pass

    # 🌟 UPDATED QR GENERATION ENGINE
    qr_base64 = None
    if selected_asset:
        asset_id_target = selected_asset.get("Assets Id", "")
        # Dynamic URL generator for local and Render production
        qr_data = f"{request.host_url.rstrip('/')}/m/asset/{asset_id_target}"
        
        qr = qrcode.QRCode(version=1, box_size=3, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1e3a8a", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    alert_count = TicketModel.query.filter_by(status="Open").count()

    return render_template(
        "index.html",
        assets=assets_list,
        selected_asset=selected_asset,  
        qr_base64=qr_base64,            
        total_assets=total_assets,
        active_assets=active_assets,
        inactive_assets=inactive_assets,
        expiring_assets=len(expiring_assets_list),
        expiring_assets_list=expiring_assets_list,
        dept_data=dept_data,
        role=current_user.role,
        alert_count=alert_count
    )

@app.route("/add", methods=["POST"])
@login_required
@role_required(['Admin', 'Technician'])
def add():
    asset_id = request.form.get("Assets_Id", "").strip()
    if not asset_id:
        return "Asset ID cannot be empty!", 400

    if AssetModel.query.get(asset_id):
        return "Error: An asset with this Asset ID already exists!", 400

    def format_form_date(field_name):
        val = request.form.get(field_name, "")
        if val:
            try:
                return datetime.strptime(val, "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                return val
        return ""

    assigned_user_name = request.form.get("User", "").strip()
    username_id = None
    
    if assigned_user_name and assigned_user_name not in ["-", "None", "STORE", "In Store"]:
        # 1. Generate base username structure (e.g., kiran_shinde)
        base_username = assigned_user_name.lower().replace(" ", "_")
        username_id = base_username
        
        # 2. 🌟 LOOKUP LOOP: Keep incrementing if this exact username is taken by another person
        counter = 2
        while db.session.get(UserModel, username_id):
            username_id = f"{base_username}{counter}"
            counter += 1
        
        # 3. Now that username_id is guaranteed completely unique, check and create the row
        user_exists = db.session.get(UserModel, username_id)
        if not user_exists:
            default_password = "Nexus@2026"  # Updated to match your system default pattern
            
            new_automatic_user = UserModel(
                username=username_id,
                password_hash=generate_password_hash(default_password),
                role="User",
                name=assigned_user_name,
                email=f"{username_id}@nexus.tech"
            )
            db.session.add(new_automatic_user)
            db.session.flush()  # 🌟 Force SQL Alchemy to create the user immediately before linking the asset
            
            # 📧 Trigger the welcome email notification targeting the unique email address
            email_body = f"""
            <h3>Welcome to Nexus Technology Industries, {assigned_user_name}!</h3>
            <p>An IT asset has been successfully assigned to you, and your profile has been provisioned.</p>
            <p><b>Your Unique Username:</b> {username_id}</p>
            <p><b>Your Default Password:</b> Nexus@2026</p>
            <br/>
            <p><i>Please log into your portal dashboard to verify your profile and update your password under system settings immediately.</i></p>
            """
            send_system_email("🎉 Your New IT Portal Account Credentials", f"{username_id}@nexus.tech", email_body)
            flash(f"🎉 Auto-Provision: Account created for {assigned_user_name}. User: {username_id}")

    new_asset = AssetModel(
        asset_id=asset_id,
        asset_type=request.form.get("Type", ""),
        brand=request.form.get("Brand", ""),
        model=request.form.get("Model", ""),
        # Assigns the safe, unique user id string to the asset record
        user=username_id if username_id else assigned_user_name,
        department=request.form.get("Department", ""),
        status=request.form.get("Status", "Active"),
        warranty_period=request.form.get("Warranty Period", ""),
        serial_no=request.form.get("Serial No", ""),
        tag_id=request.form.get("TAG Id", ""),
        warranty_expiry=format_form_date("Warranty Expiry"),
        grn_no=request.form.get("GRN_No", ""),
        grn_date=format_form_date("GRN_Date"),
        supplier_name=request.form.get("Supplier_Name", ""),
        supplier_invoice_no=request.form.get("Supplier_Invoice_No", ""),
        supplier_invoice_date=format_form_date("Supplier_Invoice_Date"),
        record_status="Active"
    )

    db.session.add(new_asset)
    add_transaction(asset_id, "Created", "New Asset Added")
    db.session.commit()
    return redirect("/assets")

@app.route("/delete", methods=["POST"])
@login_required
@role_required(['Admin'])
def delete():
    asset_id = request.form.get("asset_id", "").strip()
    asset = AssetModel.query.get(asset_id)
    if asset:
        asset.record_status = "DEL"
        asset.deleted_date = datetime.now().strftime("%d/%m/%Y")
        add_transaction(asset_id, "Deleted", "Asset Deleted")
        db.session.commit()
    return redirect("/assets")

@app.route("/update", methods=["POST"])
@login_required
@role_required(['Admin', 'Technician'])
def update():
    asset_id = request.form.get("asset_id", "").strip()
    asset = AssetModel.query.get(asset_id)
    
    if asset:
        def format_form_date(field_name):
            val = request.form.get(field_name, "")
            if val:
                try:
                    return datetime.strptime(val, "%Y-%m-%d").strftime("%d/%m/%Y")
                except Exception:
                    return val
            return ""

        asset.asset_type = request.form.get("Type", "")
        asset.brand = request.form.get("Brand", "")
        asset.model = request.form.get("Model", "")
        
        assigned_user = request.form.get("User", "").strip()
        if assigned_user and assigned_user not in ["-", "None", "STORE", "In Store"]:
            username_id = assigned_user.lower().replace(" ", "_")
            
            # Use safe session query instead of legacy get()
            user_exists = db.session.get(UserModel, username_id)
            if not user_exists:
                new_automatic_user = UserModel(
                    username=username_id,
                    password_hash=generate_password_hash("Nexus@2026"),
                    role="User",
                    name=assigned_user,
                    email=f"{username_id}@nexus.tech"
                )
                db.session.add(new_automatic_user)
                db.session.flush()  # 🌟 FORCE the database to create the user account right now
            
            asset.user = username_id
        else:
            asset.user = assigned_user

        asset.department = request.form.get("Department", "")
        asset.status = request.form.get("Status", "")
        asset.warranty_period = request.form.get("Warranty Period", "")
        asset.serial_no = request.form.get("Serial No", "")
        asset.tag_id = request.form.get("TAG Id", "")
        
        w_exp = format_form_date("Warranty Expiry")
        g_dat = format_form_date("GRN_Date")
        s_dat = format_form_date("Supplier_Invoice_Date")

        if w_exp: asset.warranty_expiry = w_exp
        if g_dat: asset.grn_date = g_dat
        if s_dat: asset.supplier_invoice_date = s_dat

        asset.record_status = "U"
        asset.updated_date = datetime.now().strftime("%d/%m/%Y")
        
        add_transaction(asset_id, "Updated", "Asset Information Updated")
        db.session.commit()
        
        # 🟢 NEW: Log this action for your Audit Trail
        log_audit("Updated asset details", asset_id)

    return redirect("/assets")

@app.route("/load_asset", methods=["POST"])
@login_required
def load_asset():
    asset_id = str(request.form.get("asset_id", "")).strip()
    target_asset = AssetModel.query.get(asset_id)

    if not target_asset or target_asset.record_status == "DEL":
        return redirect("/assets")

    def reformat_to_html_date(date_str):
        if date_str and date_str.strip() and date_str != "-":
            try:
                return datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                try:
                    return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                except Exception:
                    try:
                        return datetime.strptime(date_str.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
                    except Exception:
                        return ""
        return ""

    selected_asset = {
        "Assets Id": target_asset.asset_id, 
        "Type": target_asset.asset_type, 
        "Brand": target_asset.brand, 
        "Model": target_asset.model,
        "User": target_asset.user if target_asset.user else "-", 
        "Department": target_asset.department, 
        "Status": target_asset.status, 
        "GRN No.": target_asset.grn_no,
        "GRN Date": reformat_to_html_date(target_asset.grn_date), 
        "Supplier Name": target_asset.supplier_name, 
        "Supplier Invoice No.": target_asset.supplier_invoice_no,
        "Supplier Invoice Date": reformat_to_html_date(target_asset.supplier_invoice_date), 
        "Serial No": target_asset.serial_no, 
        "TAG Id": target_asset.tag_id,
        "Warranty Period": target_asset.warranty_period, 
        "Warranty Expiry": reformat_to_html_date(target_asset.warranty_expiry)
    }

    # Generate QR Code string on data form loading actions as well
    qr_base64 = None
    if selected_asset:
        asset_id_target = selected_asset.get("Assets Id", "")
        # Updated to dynamic URL
        qr_data = f"{request.host_url.rstrip('/')}/m/asset/{asset_id_target}"
        qr = qrcode.QRCode(version=1, box_size=3, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1e3a8a", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    all_assets = AssetModel.query.filter(AssetModel.record_status != "DEL").all()
    assets_list = []
    expiring_assets_list = []
    today = datetime.today()
    dept_data = {}

    for a in all_assets:
        row = {
            "Assets Id": a.asset_id, "Type": a.asset_type, "Brand": a.brand, "Model": a.model,
            "User": a.user if a.user else "-", "Department": a.department, "Status": a.status, "GRN No.": a.grn_no,
            "GRN Date": a.grn_date, "Supplier Name": a.supplier_name, "Supplier Invoice No.": a.supplier_invoice_no,
            "Supplier Invoice Date": a.supplier_invoice_date, "Serial No": a.serial_no, "TAG Id": a.tag_id,
            "Warranty Period": a.warranty_period, "Warranty Expiry": a.warranty_expiry
        }
        assets_list.append(row)
        if a.department:
            dept_data[a.department] = dept_data.get(a.department, 0) + 1

        if a.warranty_expiry:
            try:
                expiry_dt = datetime.strptime(a.warranty_expiry, "%d/%m/%Y")
                if (expiry_dt - today).days <= 30:
                    expiring_assets_list.append(row)
            except Exception:
                pass

    total_assets = AssetModel.query.count()
    active_assets = AssetModel.query.filter_by(status='Active').count()
    inactive_assets = AssetModel.query.filter_by(status='Inactive').count()
    alert_count = TicketModel.query.filter_by(status="Open").count()

    return render_template(
        "index.html",
        selected_asset=selected_asset,
        qr_base64=qr_base64,
        assets=assets_list,                         
        total_assets=total_assets,
        active_assets=active_assets,
        inactive_assets=inactive_assets,
        expiring_assets=len(expiring_assets_list),  
        expiring_assets_list=expiring_assets_list,
        dept_data=dept_data,
        role=current_user.role,
        alert_count=alert_count
    )

@app.route("/transactions")
@login_required
@role_required(['Admin', 'Technician'])
def transactions():
    logs = TransactionModel.query.all()
    transactions_list = [{
        "Transaction ID": l.transaction_id, "Asset ID": l.asset_id,
        "Action": l.action, "Date": l.date, "Remarks": l.remarks
    } for l in logs]
    return render_template("transactions.html", transactions=transactions_list)

@app.route("/assign_asset", methods=["GET", "POST"])
@login_required
@role_required(['Admin', 'Technician'])
def assign_asset():
    if request.method == "POST":
        asset_id = request.form.get("asset_id", "").strip()
        employee_name = request.form.get("employee_name", "").strip()
        department = request.form.get("department", "").strip()

        existing = AssignmentModel.query.filter_by(asset_id=asset_id, status="Assigned").first()
        if existing:
            return "Asset already assigned!", 400

        total_asn = AssignmentModel.query.count()
        assignment_id = f"ASN{total_asn + 1:04d}"

        new_row = AssignmentModel(
            assignment_id=assignment_id, asset_id=asset_id, employee_name=employee_name,
            department=department, assigned_date=datetime.now().strftime("%d/%m/%Y"),
            return_date="", status="Assigned"
        )
        db.session.add(new_row)

        asset = AssetModel.query.get(asset_id)
        if asset:
            asset.status = "Assigned"

        add_transaction(asset_id, "Assigned", f"Assigned to {employee_name}")
        db.session.commit()
        return redirect("/assign_asset")

    search = request.args.get("search", "").strip()
    if search:
        asns = AssignmentModel.query.filter(
            AssignmentModel.employee_name.contains(search) | 
            AssignmentModel.asset_id.contains(search) | 
            AssignmentModel.department.contains(search)
        ).all()
    else:
        asns = AssignmentModel.query.all()

    assignments_list = [{
        "Assignment ID": a.assignment_id, "Assignment_ID": a.assignment_id, "Asset ID": a.asset_id,
        "Employee Name": a.employee_name, "Department": a.department, "Assigned Date": a.assigned_date,
        "Return Date": a.return_date, "Status": a.status
    } for a in asns]

    assigned_count = AssignmentModel.query.filter_by(status="Assigned").count()
    returned_count = AssignmentModel.query.filter_by(status="Returned").count()
    instore_count = AssignmentModel.query.filter_by(status="In Store").count()
    
    asset_ids = [a.asset_id for a in AssetModel.query.filter(AssetModel.record_status != "DEL").all()]

    return render_template(
        "assign_asset.html",
        assignments=assignments_list,
        assigned_count=assigned_count,
        returned_count=returned_count,
        instore_count=instore_count,
        asset_ids=asset_ids
    )

@app.route("/return_asset/<assignment_id>")
@login_required
@role_required(['Admin', 'Technician'])
def return_asset(assignment_id):
    asn = AssignmentModel.query.get(assignment_id)
    if asn:
        asn.status = "Returned"
        asn.return_date = datetime.now().strftime("%d/%m/%Y")

        asset = AssetModel.query.get(asn.asset_id)
        if asset:
            asset.status = "Inactive"

        add_transaction(asn.asset_id, "Returned", "Asset Returned")
        db.session.commit()

    return redirect("/assign_asset")

@app.route("/transfer_asset/<assignment_id>", methods=["GET", "POST"])
@login_required
@role_required(['Admin', 'Technician'])
def transfer_asset(assignment_id):
    asn = AssignmentModel.query.get(assignment_id)
    if not asn:
        return "Assignment not found", 404

    if request.method == "POST":
        old_employee = asn.employee_name
        new_employee = request.form.get("employee_name", "").strip()
        new_department = request.form.get("department", "").strip()

        asn.employee_name = new_employee
        asn.department = new_department

        add_transaction(asn.asset_id, "Transferred", f"Transferred from {old_employee} to {new_employee}")
        db.session.commit()
        return redirect("/assign_asset")

    return render_template("transfer_asset.html", assignment={
        "Assignment ID": asn.assignment_id, "Asset ID": asn.asset_id,
        "Employee Name": asn.employee_name, "Department": asn.department
    })

@app.route("/store_asset/<assignment_id>")
@login_required
@role_required(['Admin', 'Technician'])
def store_asset(assignment_id):
    asn = AssignmentModel.query.get(assignment_id)
    if asn:
        asset_id = asn.asset_id
        asn.employee_name = "STORE"
        asn.department = "STORE"
        asn.status = "In Store"

        add_transaction(asset_id, "Stored", "Asset moved to store")
        db.session.commit()

    return redirect("/assign_asset")

@app.route("/tickets", methods=["GET", "POST"])
@login_required
def tickets():
    if request.method == "POST":
        total_tkts = TicketModel.query.count()
        ticket_id = f"TKT{total_tkts + 1:04d}"
        
        asset_id = request.form.get("asset_id", "").strip()
        target_asset = AssetModel.query.get(asset_id)
        dept = target_asset.department if target_asset else ""

        new_ticket = TicketModel(
            ticket_id=ticket_id, 
            asset_id=asset_id,
            issue=request.form.get("issue", ""), 
            raised_by=current_user.name, 
            priority=request.form.get("priority", "Medium"), 
            assigned_to="-",
            department=dept, 
            status="Open",
            created_date=datetime.now().strftime("%d/%m/%Y"), 
            closed_date="-",
            last_updated=datetime.now().strftime("%d/%m/%Y %H:%M"),
            description=request.form.get("description", ""), 
            notes=""
        )
        db.session.add(new_ticket)
        add_transaction(asset_id, "Ticket Raised", f"Issue reported: {new_ticket.issue}")
        db.session.commit()
        # 📧 If it's a critical issue, alert the Admin instantly!
        if request.form.get("priority", "Medium") == "High":
            admin_alert_body = f"""
            <h3>🚨 Critical System Ticket Alert: {new_ticket.ticket_id}</h3>
            <p><b>Asset Target ID:</b> {asset_id}</p>
            <p><b>Issue Encountered:</b> {new_ticket.issue}</p>
            <p><b>Reported By Profile:</b> {current_user.name}</p>
            <br/>
            <p>Please log into the management console to review and triage this system disruption immediately.</p>
            """
            send_system_email(f"⚠️ High Priority Ticket Notification: {new_ticket.ticket_id}", "admin@nexus.tech", admin_alert_body)
            
            # 🌟 TRIGGER INSTANT DISCORD DISPATCH
            discord_message = f"🚨 **CRITICAL TICKET ALERT [{new_ticket.ticket_id}]**\n• **Asset ID:** {asset_id}\n• **Issue:** {new_ticket.issue}\n• **Reported By:** {current_user.name}\n\n*Please check the management console immediately.*"
            send_discord_webhook(discord_message)
            
            # --- TEMPORARY AI TEST LINE ---
            ai_test_result = ai_analyze_ticket(request.form.get('issue'), request.form.get('description'))
            print(f"\n🤖 LIVE AI TRIAGE REPORT:\n{ai_test_result}\n")

        return redirect("/tickets")

    search = request.args.get("search", "").strip()
    if search:
        all_tkts = TicketModel.query.filter(
            TicketModel.ticket_id.contains(search) | 
            TicketModel.asset_id.contains(search) | 
            TicketModel.issue.contains(search)
        ).all()
    else:
        all_tkts = TicketModel.query.all()

    open_tickets = TicketModel.query.filter_by(status="Open").count()
    closed_tickets = TicketModel.query.filter_by(status="Closed").count()
    high_priority = TicketModel.query.filter_by(priority="High").count()
    in_progress_tickets = TicketModel.query.filter_by(status="In Progress").count()

    tickets_list = []
    for t in all_tkts:
        tickets_list.append({
            "Ticket ID": t.ticket_id, "Ticket_ID": t.ticket_id, "Asset ID": t.asset_id, "Issue": t.issue,
            "Raised By": t.raised_by, "Priority": t.priority, "Status": t.status, "Description": t.description,
            "Created Date": t.created_date, "Closed Date": t.closed_date, "Assigned To": t.assigned_to,
            "Department": t.department, "Notes": t.notes, "Last Updated": t.last_updated
        })

    asset_ids = [a.asset_id for a in AssetModel.query.filter(AssetModel.record_status != "DEL").all()]
    asset_data = {a.asset_id: {"user": a.user if a.user else "-", "department": a.department} for a in AssetModel.query.all()}
    alert_count = open_tickets

    return render_template(
        "tickets.html", tickets=tickets_list, open_tickets=open_tickets,
        closed_tickets=closed_tickets, in_progress_tickets=in_progress_tickets,
        high_priority=high_priority, asset_ids=asset_ids, asset_data=asset_data,
        role=current_user.role, alert_count=alert_count
    )

@app.route("/close_ticket/<ticket_id>")
@login_required
@role_required(['Admin', 'Technician'])
def close_ticket(ticket_id):
    tkt = TicketModel.query.get(ticket_id)
    if tkt:
        tkt.status = "Closed"
        tkt.closed_date = datetime.now().strftime("%d/%m/%Y")
        tkt.last_updated = datetime.now().strftime("%d/%m/%Y %H:%M")
        add_transaction(tkt.asset_id, "Ticket Closed", f"Resolved completely: {tkt.ticket_id}")
        db.session.commit()
    return redirect("/tickets")

@app.route("/reopen_ticket/<ticket_id>")
@login_required
@role_required(['Admin', 'Technician'])
def reopen_ticket(ticket_id):
    tkt = TicketModel.query.get(ticket_id)
    if tkt:
        tkt.status = "Open"
        tkt.closed_date = "-"
        tkt.last_updated = datetime.now().strftime("%d/%m/%Y %H:%M")
        db.session.commit()
    return redirect("/tickets")

@app.route("/reports")
@login_required
@role_required(['Admin', 'Technician'])
def reports():
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template(
        "reports.html",
        total_assets=AssetModel.query.count(),
        total_assignments=AssignmentModel.query.count(),
        total_tickets=TicketModel.query.count(),
        alert_count=alert_count
    )

@app.route("/ticket/<ticket_id>", methods=["GET", "POST"])
@login_required
def ticket_details(ticket_id):
    tkt = TicketModel.query.get(ticket_id)
    if not tkt:
        return "Ticket Not Found", 404

    if request.method == "POST":
        tkt.notes = request.form.get("notes", "")
        tkt.last_updated = datetime.now().strftime("%d/%m/%Y %H:%M")
        db.session.commit()
        return redirect(f"/ticket/{ticket_id}")

    ticket_dict = {
        "Ticket ID": tkt.ticket_id, "Asset ID": tkt.asset_id, "Issue": tkt.issue,
        "Raised By": tkt.raised_by, "Priority": tkt.priority, "Status": tkt.status,
        "Description": tkt.description, "Created Date": tkt.created_date,
        "Closed Date": tkt.closed_date, "Assigned To": tkt.assigned_to,
        "Department": tkt.department, "Notes": tkt.notes, "Last Updated": tkt.last_updated
    }

    history_tkts = TicketModel.query.filter(TicketModel.asset_id == tkt.asset_id, TicketModel.ticket_id != ticket_id).all()
    history = [{
        "Ticket ID": h.ticket_id, "Issue": h.issue, "Status": h.status, "Created Date": h.created_date
    } for h in history_tkts]

    alert_count = TicketModel.query.filter_by(status="Open").count()

    return render_template("ticket_details.html", ticket=ticket_dict, history=history, role=current_user.role, alert_count=alert_count)

@app.route("/start_ticket/<ticket_id>")
@login_required
@role_required(['Admin', 'Technician'])
def start_ticket(ticket_id):
    tkt = TicketModel.query.get(ticket_id)
    if tkt:
        tkt.status = "In Progress"
        tkt.assigned_to = current_user.name 
        tkt.last_updated = datetime.now().strftime("%d/%m/%Y %H:%M")
        db.session.commit()
    return redirect("/tickets")

@app.route("/spare_parts")
@login_required
def spare_parts():
    all_active = AssetModel.query.filter(AssetModel.record_status != "DEL").all()
    device_summary = {}
    main_hardware = ['Laptop', 'Desktop', 'Printer', 'Router', 'Scanner']

    for a in all_active:
        t = str(a.asset_type).capitalize()
        if t in main_hardware:
            if t not in device_summary:
                device_summary[t] = {"Active": 0, "Inactive": 0}
            if a.status in ["Active", "Inactive"]:
                device_summary[t][a.status] += 1

    active_computers = AssetModel.query.filter(AssetModel.asset_type.in_(['Laptop', 'Desktop']), AssetModel.status == 'Active').count()
    inactive_computers = AssetModel.query.filter(AssetModel.asset_type.in_(['Laptop', 'Desktop']), AssetModel.status == 'Inactive').count()

    parts_summary = {
        'RAM Sticks (Standard Bundle)': {'Active': active_computers, 'Inactive': inactive_computers},
        'Storage Drives (OS System SSD)': {'Active': active_computers, 'Inactive': inactive_computers}
    }
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template("spare_parts.html", device_summary=device_summary, parts_summary=parts_summary, alert_count=alert_count)

# --- SECURE USER MANAGEMENT PANEL ---
@app.route("/manage_users", methods=["GET", "POST"])
@login_required
@role_required(['Admin'])
def manage_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "Technician").strip()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        
        if not username or not password:
            return "Username and Password cannot be empty!", 400
            
        if UserModel.query.get(username):
            return "Error: User already exists!", 400
            
        new_user = UserModel(
            username=username, password_hash=generate_password_hash(password),
            role=role, name=name, email=email
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect("/manage_users")
        
    all_users = UserModel.query.all()
    users_list = [{
        "username": u.username, "role": u.role, "name": u.name, "email": u.email
    } for u in all_users]
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template("manage_users.html", users=users_list, alert_count=alert_count)

@app.route("/delete_user/<username>", methods=["POST"])
@login_required
@role_required(['Admin'])
def delete_user(username):
    if str(username) == str(current_user.username):
        return "Error: You cannot delete your own active session account!", 400
        
    user = UserModel.query.get(username)
    if user:
        db.session.delete(user)
        db.session.commit()
    return redirect("/manage_users")

# ==========================================
# 2. USER SELF-SERVICE INTERFACES & ROUTING
# ==========================================

@app.route("/submit_request", methods=["POST"])
@login_required
def submit_request():
    asset_type = request.form.get("asset_type", "").strip()
    purpose = request.form.get("purpose", "").strip()
    
    if not asset_type:
        return "Asset Type is required!", 400
        
    total_reqs = RequestModel.query.count()
    request_id = f"REQ{total_reqs + 1:04d}"
    
    new_req = RequestModel(
        request_id=request_id,
        requested_by=current_user.username,
        asset_type=asset_type,
        purpose=purpose,
        date_submitted=datetime.now().strftime("%d/%m/%Y"),
        status="Pending"
    )
    db.session.add(new_req)
    db.session.commit()
    return redirect("/portal")

@app.route("/manage_requests")
@login_required
@role_required(['Admin'])
def manage_requests():
    reqs = RequestModel.query.all()
    requests_list = [{
        "request_id": r.request_id, "requested_by": r.requested_by,
        "asset_type": r.asset_type, "purpose": r.purpose,
        "date_submitted": r.date_submitted, "status": r.status
    } for r in reqs]
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template("manage_requests.html", requests=requests_list, alert_count=alert_count)

@app.route("/action_request/<request_id>/<action_status>")
@login_required
@role_required(['Admin'])
def action_request(request_id, action_status):
    req = RequestModel.query.get(request_id)
    if req and action_status in ["Approved", "Rejected"]:
        req.status = action_status
        if action_status == "Approved":
            add_transaction("REQ-SYS", "Request Approved", f"Authorized procurement of {req.asset_type} for user {req.requested_by}")
        db.session.commit()
    return redirect("/manage_requests")

# ==========================================
# 3. ADMINISTRATIVE SNAPSHOT BACKUP CONTROLLER
# ==========================================

@app.route("/backup_database")
@login_required
@role_required(['Admin'])
def backup_database():
    import sqlite3
    try:
        backup_dir = os.path.join(os.getcwd(), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_file = os.path.join(backup_dir, f"backup_{timestamp}.db")
        
        local_conn = sqlite3.connect(dest_file)
        local_cursor = local_conn.cursor()
        
        # 1. CREATE TABLES
        local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY, asset_type TEXT, brand TEXT, model TEXT,
                user TEXT, department TEXT, status TEXT, record_status TEXT
            );
        """)
        local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, password TEXT, role TEXT, record_status TEXT
            );
        """)
        local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                assignment_id TEXT PRIMARY KEY, asset_id TEXT, employee_name TEXT,
                department TEXT, assigned_date TEXT, return_date TEXT, status TEXT
            );
        """)
        local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY, asset_id TEXT, issue TEXT,
                raised_by TEXT, priority TEXT, status TEXT, last_updated TEXT
            );
        """)
        local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY, asset_id TEXT, action TEXT,
                date TEXT, remarks TEXT
            );
        """)
        
        # 2. POPULATE DATA
        for asset in AssetModel.query.all():
            local_cursor.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?);", 
                (asset.asset_id, asset.asset_type, asset.brand, asset.model, asset.user, asset.department, asset.status, asset.record_status))
            
        for u in UserModel.query.all():
            local_cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?);", 
                (u.username, u.password_hash, u.role, "Active"))
            
        for a in AssignmentModel.query.all():
            local_cursor.execute("INSERT INTO assignments VALUES (?, ?, ?, ?, ?, ?, ?);", 
                (a.assignment_id, a.asset_id, a.employee_name, a.department, str(a.assigned_date), str(a.return_date), a.status))
            
        for t in TicketModel.query.all():
            local_cursor.execute("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?);", 
                (t.ticket_id, t.asset_id, t.issue, t.raised_by, t.priority, t.status, str(t.last_updated)))
            
        for tx in TransactionModel.query.all():
            local_cursor.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?);", 
                (tx.transaction_id, tx.asset_id, tx.action, str(tx.date), tx.remarks))
            
        local_conn.commit()
        local_conn.close()
        
        return send_file(dest_file, as_attachment=True, download_name=f"system_backup_{timestamp}.db")
        
    except Exception as e:
        return f"Infrastructure backup routine error: {str(e)}", 500

# ==========================================
# CENTRAL REPORTING ENGINES (VIEW & DOWNLOAD)
# ==========================================

def get_report_data(report_type):
    headers = []
    rows = []
    
    if report_type == "assets":
        headers = ["Asset ID", "Type", "Brand", "Model", "User", "Department", "Status"]
        records = AssetModel.query.filter(AssetModel.record_status != "DEL").all()
        for r in records:
            rows.append([r.asset_id, r.asset_type, r.brand, r.model, r.user if r.user else "-", r.department, r.status])
            
    elif report_type == "assignments":
        headers = ["Assignment ID", "Asset ID", "Employee Name", "Department", "Assigned Date", "Return Date", "Status"]
        records = AssignmentModel.query.all()
        for r in records:
            rows.append([r.assignment_id, r.asset_id, r.employee_name, r.department, r.assigned_date, r.return_date, r.status])
            
    elif report_type == "tickets":
        headers = ["Ticket ID", "Asset ID", "Issue", "Raised By", "Priority", "Status", "Last Updated"]
        records = TicketModel.query.order_by(TicketModel.status.desc(), TicketModel.last_updated.desc()).all()
        for r in records:
            rows.append([r.ticket_id, r.asset_id, r.issue, r.raised_by, r.priority, r.status, r.last_updated])
            
    elif report_type == "transactions":
        headers = ["Transaction ID", "Asset ID", "Action", "Date", "Remarks"]
        records = TransactionModel.query.all()
        for r in records:
            rows.append([r.transaction_id, r.asset_id, r.action, r.date, r.remarks])
            
    return headers, rows

@app.route("/view_report", methods=["GET"])
@login_required
@role_required(['Admin', 'Technician'])
def view_report():
    report_type = request.args.get("report_type", "").strip()
    headers, rows = get_report_data(report_type)
    
    if not headers:
        return redirect("/reports")
        
    html_content = f"""
    <html>
    <head>
        <title>Inline Report Viewer</title>
        <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/jspdf-autotable@3.6.0/dist/jspdf.plugin.autotable.min.js"></script>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 30px; background: #f4f7fc; color: #333; }}
            h2 {{ color: #1e40af; text-transform: capitalize; margin-bottom: 5px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; background: white; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            th {{ background: #1e3a8a; color: white; padding: 12px; text-align: left; }}
            td {{ padding: 10px; border-bottom: 1px solid #e5e7eb; }}
            tr:nth-child(even) {{ background: #f8fafc; }}
            .controls-row {{ display: flex; align-items: center; justify-content: space-between; background: white; padding: 15px 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); margin-top: 20px; gap: 15px; flex-wrap: wrap; }}
            .filter-group {{ display: flex; align-items: center; gap: 10px; }}
            .back-btn {{ background: #1e3a8a; color: white; border: none; padding: 10px 18px; border-radius: 8px; cursor: pointer; text-decoration: none; font-weight: bold; font-size: 14px; }}
            .download-excel-btn {{ background: #16a34a; color: white; border: none; padding: 10px 15px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 14px; margin-right: 8px; }}
            .download-excel-btn:hover {{ background: #15803d; }}
            .download-pdf-btn {{ background: #dc2626; color: white; border: none; padding: 10px 15px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 14px; }}
            .download-pdf-btn:hover {{ background: #b91c1c; }}
            .search-box {{ padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; width: 180px; box-sizing: border-box; }}
            label {{ font-weight: 600; font-size: 13px; color: #475569; }}
        </style>
    </head>
    <body>
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2>📋 Live Data Feed Summary: {report_type}</h2>
            <a href="/reports" class="back-btn">← Back to Reports</a>
        </div>
        
        <div class="controls-row">
            <div class="filter-group">
                <label>Search by Asset ID:</label>
                <input type="text" id="assetIdSearch" class="search-box" onkeyup="filterViewerTable()" placeholder="Enter Asset ID...">
            </div>
            
            <div class="filter-group">
                <label>Start Date:</label>
                <input type="date" id="startDate" class="search-box" onchange="filterViewerTable()">
                <label>End Date:</label>
                <input type="date" id="endDate" class="search-box" onchange="filterViewerTable()">
            </div>

            <div>
                <button onclick="downloadFilteredExcel('{report_type}')" class="download-excel-btn">📊 Download Excel</button>
                <button onclick="downloadFilteredPDF('{report_type}')" class="download-pdf-btn">📄 Download PDF</button>
            </div>
        </div>

        <table id="reportViewerTable">
            <thead>
                <tr>{"".join(f"<th>{h}</th>" for h in headers)}</tr>
            </thead>
            <tbody>
                {"".join(f"<tr>{''.join(f'<td>{str(cell)}</td>' for cell in row)}</tr>" for row in rows)}
            </tbody>
        </table>

        <script>
            function parseUIDate(dateStr) {{
                if (!dateStr || dateStr.trim() === "" || dateStr === "-") return null;
                let cleanStr = dateStr.split(" ")[0];
                let parts = cleanStr.split("/");
                if (parts.length === 3) {{
                    return new Date(parts[2], parts[1] - 1, parts[0]);
                }}
                let isoParts = cleanStr.split("-");
                if (isoParts.length === 3) {{
                    return new Date(isoParts[0], isoParts[1] - 1, isoParts[2]);
                }}
                return null;
            }}

            function filterViewerTable() {{
                let assetInput = document.getElementById("assetIdSearch").value.toLowerCase().trim();
                let startInput = document.getElementById("startDate").value;
                let endInput = document.getElementById("endDate").value;
                
                let startFilterDate = startInput ? new Date(startInput) : null;
                let endFilterDate = endInput ? new Date(endInput) : null;
                if(endFilterDate) endFilterDate.setHours(23,59,59,999);

                let table = document.getElementById("reportViewerTable");
                let trs = table.getElementsByTagName("tbody")[0].getElementsByTagName("tr");
                let headers = table.getElementsByTagName("th");

                let assetColumnIndex = 0;
                for (let h = 0; h < headers.length; h++) {{
                    let hText = headers[h].innerText.toLowerCase();
                    if (hText.includes("asset id") || hText.includes("assets id")) {{
                        assetColumnIndex = h;
                        break;
                    }}
                }}

                for (let i = 0; i < trs.length; i++) {{
                    let cells = trs[i].getElementsByTagName("td");
                    if (cells.length === 0) continue;

                    let assetIdText = cells[assetColumnIndex] ? cells[assetColumnIndex].innerText.toLowerCase().trim() : "";
                    let matchesAsset = assetInput === "" || assetIdText.indexOf(assetInput) > -1;

                    let matchesDateRange = true;
                    if (startFilterDate || endFilterDate) {{
                        let dateFound = false;
                        let validDateInRow = null;

                        for (let j = 0; j < cells.length; j++) {{
                            let parsed = parseUIDate(cells[j].innerText);
                            if (parsed && !isNaN(parsed.getTime())) {{
                                validDateInRow = parsed;
                                dateFound = true;
                            }}
                        }}

                        if (dateFound && validDateInRow) {{
                            if (startFilterDate && validDateInRow < startFilterDate) matchesDateRange = false;
                            if (endFilterDate && validDateInRow > endFilterDate) matchesDateRange = false;
                        }} else {{
                            matchesDateRange = false;
                        }}
                    }}

                    trs[i].style.display = (matchesAsset && matchesDateRange) ? "" : "none";
                }}
            }}

            function downloadFilteredExcel(filename) {{
                let table = document.getElementById("reportViewerTable");
                let headers = [];
                let ths = table.getElementsByTagName("th");
                for (let i = 0; i < ths.length; i++) {{
                    headers.push(ths[i].innerText);
                }}

                let rows = [headers];
                let trs = table.getElementsByTagName("tbody")[0].getElementsByTagName("tr");
                for (let i = 0; i < trs.length; i++) {{
                    if (trs[i].style.display !== "none") {{
                        let rowData = [];
                        let tds = trs[i].getElementsByTagName("td");
                        for (let j = 0; j < tds.length; j++) {{
                            rowData.push(tds[j].innerText);
                        }}
                        rows.push(rowData);
                    }}
                }}

                let wb = XLSX.utils.book_new();
                let ws = XLSX.utils.aoa_to_sheet(rows);
                XLSX.utils.book_append_sheet(wb, ws, "Filtered Report");
                XLSX.writeFile(wb, filename + "_filtered_report.xlsx");
            }}

            function downloadFilteredPDF(filename) {{
                const {{ jsPDF }} = window.jspdf;
                let doc = new jsPDF({{ orientation: "landscape" }});
                
                doc.setFontSize(16);
                doc.text("Nexus Technology Industries — Filtered Custom Summary", 14, 15);
                doc.setFontSize(10);
                doc.text("Generated Profile Category: " + filename.toUpperCase(), 14, 22);

                let table = document.getElementById("reportViewerTable");
                let headers = [];
                let ths = table.getElementsByTagName("th");
                for (let i = 0; i < ths.length; i++) {{
                    headers.push(ths[i].innerText);
                }}

                let bodyRows = [];
                let trs = table.getElementsByTagName("tbody")[0].getElementsByTagName("tr");
                for (let i = 0; i < trs.length; i++) {{
                    if (trs[i].style.display !== "none") {{
                        let rowData = [];
                        let tds = trs[i].getElementsByTagName("td");
                        for (let j = 0; j < tds.length; j++) {{
                            rowData.push(tds[j].innerText);
                        }}
                        bodyRows.push(rowData);
                    }}
                }}

                doc.autoTable({{
                    head: [headers],
                    body: bodyRows,
                    startY: 28,
                    theme: "grid",
                    headStyles: {{ fillColor: [30, 58, 138] }},
                    styles: {{ fontSize: 9, halign: "center" }}
                }});

                doc.save(filename + "_filtered_report.pdf");
            }}
        </script>
    </body>
    </html>
    """
    return html_content

@app.route("/download_report", methods=["GET"])
@login_required
@role_required(['Admin', 'Technician'])
def download_report():
    report_type = request.args.get("report_type", "").strip()
    fmt = request.args.get("format", "pdf").strip()
    
    headers, rows = get_report_data(report_type)
    if not headers:
        return redirect("/reports")
        
    if fmt == "excel":
        import pandas as pd
        df = pd.DataFrame(rows, columns=headers)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=report_type.capitalize())
        buffer.seek(0)
        return send_file(
            buffer, 
            as_attachment=True, 
            download_name=f"{report_type}_report.xlsx", 
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    else:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        
        story = [
            Paragraph(f"<b>Nexus Technology Industries — Custom Report ({report_type.capitalize()})</b>", styles['Title']), 
            Spacer(1, 15)
        ]
        
        table_data = [headers] + rows
        t = Table(table_data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e3a8a')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('BOTTOMPADDING', (0,0), (-1,0), 8),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ]))
        story.append(t)
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer, 
            as_attachment=True, 
            download_name=f"{report_type}_report.pdf", 
            mimetype="application/pdf"
        )

# 🌟 CUSTOM RESPONSTRUCTED DEVICE MOBILE GATEWAY
@app.route("/m/asset/<asset_id>")
@login_required
def mobile_asset_passport(asset_id):
    asset = AssetModel.query.filter_by(asset_id=asset_id).first_or_404()
    tickets = TicketModel.query.filter_by(asset_id=asset_id).order_by(TicketModel.ticket_id.desc()).limit(3).all()
    
    return render_template(
        "mobile_passport.html",
        asset=asset,
        tickets=tickets,
        role=current_user.role
    )

@app.route("/download_sticker/<asset_id>")
@login_required
def download_sticker(asset_id):
    asset = AssetModel.query.get_or_404(asset_id)
    
    qr_data = f"{request.host_url.rstrip('/')}/m/asset/{asset.asset_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1e3a8a", back_color="white")
    qr_buffer = BytesIO()
    img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    
    pdf_buffer = BytesIO()
    
    from reportlab.lib.pagesizes import inch
    sticker_width = 3.2 * inch
    sticker_height = 2.0 * inch
    
    doc = SimpleDocTemplate(
        pdf_buffer, 
        pagesize=(sticker_width, sticker_height),
        leftMargin=10, rightMargin=10, topMargin=10, bottomMargin=10
    )
    
    styles = getSampleStyleSheet()
    
    style_title = Paragraph(f"<b>NEXUS INDUSTRIES LTD.</b>", styles['Normal'])
    style_title.fontSize = 9
    style_title.textColor = colors.HexColor('#1e3a8a')
    
    style_details = Paragraph(
        f"<b>ID:</b> {asset.asset_id}<br/>"
        f"<b>Type:</b> {asset.asset_type}<br/>"
        f"<b>Model:</b> {asset.brand} {asset.model if asset.model else ''}", 
        styles['Normal']
    )
    style_details.fontSize = 8
    style_details.leading = 11
    
    from reportlab.platypus import Image as RLImage
    qr_img_flowable = RLImage(qr_buffer, width=1.1*inch, height=1.1*inch)
    
    sticker_table_data = [
        [qr_img_flowable, [style_title, Spacer(1, 6), style_details]]
    ]
    
    label_table = Table(sticker_table_data, colWidths=[1.2*inch, 1.7*inch])
    label_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,0), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    
    story = [label_table]
    doc.build(story)
    pdf_buffer.seek(0)
    
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"sticker_{asset.asset_id}.pdf",
        mimetype="application/pdf"
    )

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "update_profile":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            
            if name and email:
                current_user.name = name
                current_user.email = email
                db.session.commit()
                flash("✅ Profile details updated successfully!", "success")
            else:
                flash("❌ Name and Email cannot be empty.", "error")
                
        elif action == "change_password":
            current_password = request.form.get("current_password", "").strip()
            new_password = request.form.get("new_password", "").strip()
            confirm_password = request.form.get("confirm_password", "").strip()
            
            if not check_password_hash(current_user.password_hash, current_password):
                flash("❌ Current password is incorrect.", "error")
            elif new_password != confirm_password:
                flash("❌ New passwords do not match.", "error")
            elif len(new_password) < 4:
                flash("❌ Password must be at least 4 characters long.", "error")
            else:
                current_user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash("🔒 Password changed successfully!", "success")
                
        return redirect("/settings")

    return render_template("settings.html")

@app.route('/get_asset_details/<asset_id>')
@login_required
def get_asset_details(asset_id):
    asset = AssetModel.query.filter_by(asset_id=asset_id).first()
    if asset:
        return jsonify({
            'user': asset.user if asset.user else "Not Assigned",
            'department': asset.department if asset.department else "N/A"
        })
    return jsonify({'user': '', 'department': ''})

@app.route("/audit_logs")
@login_required
@role_required(['Admin'])
def audit_logs():
    logs = AuditLogModel.query.order_by(AuditLogModel.id.desc()).all()
    alert_count = TicketModel.query.filter_by(status="Open").count()
    return render_template("audit_logs.html", logs=logs, role=current_user.role, alert_count=alert_count)

def auto_provision_users():
    """Scan all assets and create user accounts for anyone missing one."""
    print("🔄 Running Auto-Provisioning for asset members...")
    all_assets = AssetModel.query.all()
    unique_usernames = {a.user for a in all_assets if a.user and a.user not in ["-", "None", "STORE", "In Store"]}
    
    count = 0
    for username in unique_usernames:
        if not UserModel.query.get(username):
            new_user = UserModel(
                username=username,
                password_hash=generate_password_hash("Nexus@2026"),
                role="User",
                name=username.replace("_", " ").title(),
                email=f"{username}@nexus.tech"
            )
            db.session.add(new_user)
            count += 1
    
    if count > 0:
        db.session.commit()
        print(f"✅ Auto-provisioned {count} new user accounts.")
    else:
        print("ℹ️ No new users to provision.")        

# --- FINAL ROBUST DATABASE INITIALIZATION ---
with app.app_context():
    try:
        db.create_all()
        if not UserModel.query.get("admin"):
            admin_user = UserModel(username="admin", password_hash=generate_password_hash("admin123"), role="Admin", name="System Administrator", email="admin@nexus.tech")
            tech1_user = UserModel(username="tech1", password_hash=generate_password_hash("tech123"), role="Technician", name="IT Support Tech 1", email="tech1@nexus.tech")
            user1_user = UserModel(username="user1", password_hash=generate_password_hash("user123"), role="User", name="Standard User 1", email="user1@nexus.tech")
            db.session.add_all([admin_user, tech1_user, user1_user])
            db.session.commit()
            print("System accounts seeded successfully.")
            
        auto_provision_users()
            
    except Exception as e:
        print(f"Initialization error: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)