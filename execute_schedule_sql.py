from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

print("=== IMPORTING SCHEDULE TO DATABASE ===\n")

# Read the SQL file
print("Reading populate_schedule.sql...")
with open('populate_schedule.sql', 'r') as f:
    sql_content = f.read()

# Connect to database
conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

conn.autocommit = True
cur = conn.cursor()

print("Executing SQL...")
try:
    cur.execute(sql_content)
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
    # Try statement by statement
    print("\nTrying statement by statement...")
    statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]
    for i, stmt in enumerate(statements):
        try:
            cur.execute(stmt)
            if (i + 1) % 100 == 0:
                print(f"  Executed {i + 1} statements...")
        except Exception as stmt_err:
            print(f"  Error on statement {i}: {stmt_err}")

# Verify
cur.execute("SELECT COUNT(*) FROM quick_start_schedule WHERE scenario_id = 1")
count = cur.fetchone()[0]
print(f"\nTotal games in schedule: {count}")

conn.close()
print("\nDone!")
