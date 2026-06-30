import os
import pandas as pd
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Initialize a temporary minimal Flask app context for SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# 1. DEFINE SECURE SQL DATABASE SCHEMAS
# ==========================================

class UserModel(db.Model):
    __tablename__ = 'users'
    username = db.Column(db.String(100), primary_key=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)

class AssetModel(db.Model):
    __tablename__ = 'assets'
    asset_id = db.Column(db.String(100), primary_key=True)
    asset_type = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    model = db.Column(db.String(100))
    
    # 🌟 MATCHED: Aligned the foreign key constraint logic with app.py
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

# ==========================================
# 2. RUN PORTING ENGINES
# ==========================================

def migrate_data():
    with app.app_context():
        print("🛠️ Initializing SQLite database structures...")
        db.create_all()
        
        # 1. Migrate Users Table
        if os.path.exists("users.xlsx"):
            print("👤 Porting accounts registry...")
            df = pd.read_excel("users.xlsx").fillna("")
            for _, row in df.iterrows():
                if not UserModel.query.filter_by(username=str(row['username'])).first():
                    db.session.add(UserModel(
                        username=str(row['username']),
                        password_hash=str(row['password_hash']),
                        role=str(row['role']),
                        name=str(row['name']),
                        email=str(row['email'])
                    ))
            db.session.commit()

        # 2. Migrate Assets Table
        if os.path.exists("assets.xlsx"):
            print("📦 Porting active warehouse assets inventory...")
            df = pd.read_excel("assets.xlsx").fillna("")
            for _, row in df.iterrows():
                if not AssetModel.query.filter_by(asset_id=str(row['Assets Id'])).first():
                    
                    # Convert raw employee name strings to lower case usernames to align with relational foreign key
                    raw_user = str(row['User']).strip()
                    if raw_user and raw_user not in ["-", "None", "STORE", "In Store"]:
                        mapped_username = raw_user.lower().replace(" ", "_")
                    else:
                        mapped_username = raw_user

                    db.session.add(AssetModel(
                        asset_id=str(row['Assets Id']),
                        asset_type=str(row['Type']),
                        brand=str(row['Brand']),
                        model=str(row['Model']),
                        user=mapped_username,
                        department=str(row['Department']),
                        status=str(row['Status']),
                        warranty_period=str(row['Warranty Period']),
                        serial_no=str(row['Serial No']),
                        tag_id=str(row['TAG Id']),
                        warranty_expiry=str(row['Warranty Expiry']),
                        grn_no=str(row['GRN No.']),
                        grn_date=str(row['GRN Date']),
                        supplier_name=str(row['Supplier Name']),
                        supplier_invoice_no=str(row['Supplier Invoice No.']),
                        supplier_invoice_date=str(row['Supplier Invoice Date']),
                        record_status=str(row.get('Record Status', 'Active')),
                        deleted_date=str(row.get('Deleted Date', '')),
                        updated_date=str(row.get('Updated Date', ''))
                    ))
            db.session.commit()

        # 3. Migrate Assignments Table
        if os.path.exists("assignments.xlsx"):
            print("🤝 Porting historical deployment handovers...")
            df = pd.read_excel("assignments.xlsx").fillna("")
            for _, row in df.iterrows():
                if not AssignmentModel.query.filter_by(assignment_id=str(row['Assignment ID'])).first():
                    db.session.add(AssignmentModel(
                        assignment_id=str(row['Assignment ID']),
                        asset_id=str(row['Asset ID']),
                        employee_name=str(row['Employee Name']),
                        department=str(row['Department']),
                        assigned_date=str(row['Assigned Date']),
                        return_date=str(row['Return Date']),
                        status=str(row['Status'])
                    ))
            db.session.commit()

        # 4. Migrate Tickets Table
        if os.path.exists("tickets.xlsx"):
            print("🎫 Porting engineering support logs...")
            df = pd.read_excel("tickets.xlsx").fillna("")
            for _, row in df.iterrows():
                if not TicketModel.query.filter_by(ticket_id=str(row['Ticket ID'])).first():
                    db.session.add(TicketModel(
                        ticket_id=str(row['Ticket ID']),
                        asset_id=str(row['Asset ID']),
                        issue=str(row['Issue']),
                        raised_by=str(row['Raised By']),
                        priority=str(row['Priority']),
                        status=str(row['Status']),
                        description=str(row['Description']),
                        created_date=str(row['Created Date']),
                        closed_date=str(row['Closed Date']),
                        assigned_to=str(row['Assigned To']),
                        department=str(row['Department']),
                        notes=str(row['Notes']),
                        last_updated=str(row['Last Updated'])
                    ))
            db.session.commit()

        # 5. Migrate Transactions Table
        if os.path.exists("transactions.xlsx"):
            print("📜 Porting central system audit logs...")
            df = pd.read_excel("transactions.xlsx").fillna("")
            for _, row in df.iterrows():
                if not TransactionModel.query.filter_by(transaction_id=str(row['Transaction ID'])).first():
                    db.session.add(TransactionModel(
                        transaction_id=str(row['Transaction ID']),
                        asset_id=str(row['Asset ID']),
                        action=str(row['Action']),
                        date=str(row['Date']),
                        remarks=str(row['Remarks'])
                    ))
            db.session.commit()

        print("🎉 Database migration completed successfully! 'database.db' is ready.")

if __name__ == "__main__":
    migrate_data()