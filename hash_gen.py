from werkzeug.security import generate_password_hash

# Set the temporary passwords you want to look up or test here
admin_pass = "admin123"
tech_pass = "tech123"

print("-----------------------------------------------")
print("🔒 WERKZEUG SECURE CRYPTOGRAPHIC HASH GENERATOR")
print("-----------------------------------------------")
print(f"Admin Text: {admin_pass}")
print(f"Generated Hash:\n{generate_password_hash(admin_pass)}")
print("\n" + "="*50 + "\n")
print(f"Tech Text: {tech_pass}")
print(f"Generated Hash:\n{generate_password_hash(tech_pass)}")
print("-----------------------------------------------")
print("💡 Note: Running this script again will produce a completely different string")
print("because Werkzeug adds a random secure salt automatically every time!")
print("-----------------------------------------------")