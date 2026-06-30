import pandas as pd
from app import app, db, UserModel, generate_password_hash

def generate_roster():
    with app.app_context():
        print("📊 Opening assets.xlsx spreadsheet...")
        try:
            # Load your excel file
            df = pd.read_excel("assets.xlsx")
        except Exception as e:
            print(f"❌ Error: Could not find or read assets.xlsx. Make sure the file name matches perfectly. ({e})")
            return

        # Ensure the 'User' column exists
        if 'User' not in df.columns:
            print("❌ Error: Could not find a column named 'User' in your spreadsheet.")
            return

        # Get all unique names, dropping empty cells or placeholders
        raw_names = df['User'].dropna().unique()
        
        print(f"✨ Found {len(raw_names)} unique values in the User column. Processing accounts...")
        
        account_count = 0
        for raw_name in raw_names:
            clean_name = str(raw_name).strip()
            
            # Skip empty markers, systemic stores, or default lines
            if not clean_name or clean_name in ["-", "None", "STORE", "In Store"]:
                continue
                
            # Create a clean username (e.g., "John Doe" -> "john_doe")
            username_id = clean_name.lower().replace(" ", "_")
            
            # Check if this user already exists in the database so we don't duplicate them
            existing_user = UserModel.query.get(username_id)
            if not existing_user:
                # Set up their default password string
                default_password = "welcome2026"
                
                new_user = UserModel(
                    username=username_id,
                    password_hash=generate_password_hash(default_password),
                    role="User",  # Defaulting their system privilege tier to regular User
                    name=clean_name,
                    email=f"{username_id}@nexus.tech"  # Generates a clean placeholder email
                )
                db.session.add(new_user)
                account_count += 1
                print(f"✅ Provisioned: {clean_name} -> Username: {username_id} | Password: {default_password}")
        
        if account_count > 0:
            db.session.commit()
            print(f"\n🎉 Successfully injected {account_count} new user accounts directly into database.db!")
        else:
            print("\nℹ️ No new user profiles needed to be created.")

if __name__ == "__main__":
    generate_roster()