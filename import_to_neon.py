import psycopg2

# Replace this with your Neon connection string
NEON_CONNECTION_STRING = "postgresql://neondb_owner:npg_lcxoET8Ory5I@ep-late-breeze-adynrcbm-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Read the SQL file
print("Reading basketball2026.sql...")
try:
    with open('basketball2026.sql', 'r', encoding='utf-8') as f:
        sql_content = f.read()
except UnicodeDecodeError:
    # Try with latin-1 encoding instead
    print("UTF-8 failed, trying latin-1 encoding...")
    with open('basketball2026.sql', 'r', encoding='latin-1') as f:
        sql_content = f.read()

# Clean SQL: Remove psql metacommands
print("Cleaning SQL file...")
lines = sql_content.split('\n')
cleaned_lines = []
for line in lines:
    # Skip psql metacommands (lines starting with backslash)
    if line.strip().startswith('\\'):
        continue
    # Skip comments
    if line.strip().startswith('--'):
        continue
    cleaned_lines.append(line)

sql_content = '\n'.join(cleaned_lines)

# Connect to Neon
print("Connecting to Neon...")
conn = psycopg2.connect(NEON_CONNECTION_STRING)
conn.autocommit = True
cur = conn.cursor()

# Execute the SQL
print("Importing database... (this may take a minute)")
try:
    cur.execute(sql_content)
    print("✓ Database imported successfully!")
except Exception as e:
    print(f"Error: {e}")
    print("\nTrying to execute statements one by one...")

    # Split into individual statements and execute
    statements = [s.strip() for s in sql_content.split(';') if s.strip()]
    success_count = 0
    error_count = 0

    for i, stmt in enumerate(statements):
        try:
            cur.execute(stmt)
            success_count += 1
            if (i + 1) % 100 == 0:
                print(f"  Executed {i + 1}/{len(statements)} statements...")
        except Exception as stmt_error:
            error_count += 1
            # Only print first few errors to avoid spam
            if error_count <= 5:
                print(f"  Warning: {str(stmt_error)[:100]}")

    print(f"\n✓ Completed: {success_count} successful, {error_count} errors")

# Verify what got imported
print("\n--- Verification ---")
try:
    # Check what tables exist
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = cur.fetchall()

    if tables:
        print(f"✓ Found {len(tables)} tables:")
        for table in tables[:10]:  # Show first 10
            print(f"  - {table[0]}")
        if len(tables) > 10:
            print(f"  ... and {len(tables) - 10} more")

        # Try to count rows in a few key tables
        try:
            cur.execute("SELECT COUNT(*) FROM leagues")
            print(f"\n✓ Leagues: {cur.fetchone()[0]} rows")
        except:
            print("\n⚠ No data in leagues table yet")

        try:
            cur.execute("SELECT COUNT(*) FROM league_teams")
            print(f"✓ Teams: {cur.fetchone()[0]} rows")
        except:
            pass
    else:
        print("⚠ No tables found - import may have failed")
        print("Try re-exporting with INSERT commands option enabled")

except Exception as e:
    print(f"Error during verification: {e}")

cur.close()
conn.close()
print("\nDone!")
