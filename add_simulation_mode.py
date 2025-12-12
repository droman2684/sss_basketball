from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

cur = conn.cursor()

print("Adding simulation_mode column to leagues table...")

try:
    cur.execute("""
        ALTER TABLE leagues
        ADD COLUMN IF NOT EXISTS simulation_mode VARCHAR(20) DEFAULT 'detailed'
    """)
    conn.commit()
    print("Success! Column added.")
    print("\nSimulation modes:")
    print("  'detailed' - Full possession-by-possession simulation (slower, more events)")
    print("  'fast' - Quick simulation with stats only (10-20x faster)")
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()

conn.close()
