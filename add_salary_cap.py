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

print("Adding salary_cap column to leagues table...")

try:
    # Add salary cap column with default NBA cap (~$140M)
    cur.execute("""
        ALTER TABLE leagues
        ADD COLUMN IF NOT EXISTS salary_cap BIGINT DEFAULT 140000000
    """)
    conn.commit()
    print("Success! salary_cap column added (default: $140,000,000)")
except Exception as e:
    print(f"Error: {e}")
    conn.rollback()

conn.close()
