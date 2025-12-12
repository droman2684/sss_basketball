from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

try:
    conn = psycopg2.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        host=os.getenv('DB_HOST'),
        sslmode='require'
    )
    cur = conn.cursor()
    cur.execute('SELECT version()')
    version = cur.fetchone()[0]

    print("Connected to Neon successfully!")
    print(f"PostgreSQL version: {version[:60]}")

    # Check for tables
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public'
    """)
    table_count = cur.fetchone()[0]
    print(f"Number of tables: {table_count}")

    conn.close()
    print("\nConnection test passed!")

except Exception as e:
    print(f"Connection failed: {e}")
