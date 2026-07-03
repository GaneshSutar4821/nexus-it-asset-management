import os
from sqlalchemy import create_engine, text

# PASTE YOUR CLOUD CONNECTION STRING HERE
cloud_url ="postgresql://nexus_db_z7ew_user:INBU9yEou8WO1YmbgEHLO5zKf72ezpcY@dpg-d92afrho3t8c73b8hhng-a.ohio-postgres.render.com/nexus_db_z7ew"

engine = create_engine(cloud_url)
try:
    connection = engine.connect()
    print("SUCCESS! I am connected to the Cloud Database.")
    result = connection.execute(text("SELECT * FROM assets;"))
    for row in result:
        print(row)
    connection.close()
except Exception as e:
    print(f"FAILED: {e}")