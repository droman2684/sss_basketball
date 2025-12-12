from dotenv import load_dotenv
import os
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

cur = conn.cursor(cursor_factory=RealDictCursor)

print("=== CHECKING LEAGUES TABLE SCHEMA ===\n")

# Check columns in leagues table
cur.execute("""
    SELECT column_name, data_type, column_default
    FROM information_schema.columns
    WHERE table_name = 'leagues'
    ORDER BY ordinal_position
""")

columns = cur.fetchall()

print("Columns in 'leagues' table:")
for col in columns:
    default = col['column_default'] or 'NULL'
    print(f"  {col['column_name']:30s} {col['data_type']:20s} DEFAULT: {default}")

# Check if simulation_mode and salary_cap exist
has_sim_mode = any(col['column_name'] == 'simulation_mode' for col in columns)
has_salary_cap = any(col['column_name'] == 'salary_cap' for col in columns)

print(f"\n✓ simulation_mode exists: {has_sim_mode}")
print(f"✓ salary_cap exists: {has_salary_cap}")

if not has_sim_mode or not has_salary_cap:
    print("\n⚠️  Missing columns! Run migrations:")
    if not has_sim_mode:
        print("  python add_simulation_mode.py")
    if not has_salary_cap:
        print("  python add_salary_cap.py")

# Test INSERT
print("\n=== TESTING INSERT ===")
try:
    cur.execute("""
        INSERT INTO leagues (name, scenario_source_id, playoff_teams_per_conf, salary_cap, sim_date)
        VALUES ('TEST LEAGUE', 1, 8, 140000000, '2024-10-22') RETURNING league_id;
    """)
    test_league_id = cur.fetchone()['league_id']
    print(f"✓ Test INSERT successful! League ID: {test_league_id}")

    # Clean up test
    cur.execute("DELETE FROM leagues WHERE league_id = %s", (test_league_id,))
    conn.commit()
    print("✓ Test league deleted")
except Exception as e:
    print(f"✗ INSERT failed: {e}")
    conn.rollback()

conn.close()
