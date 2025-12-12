import pandas as pd
from dotenv import load_dotenv
import os
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

print("=== IMPORTING REAL NBA ROSTERS FROM EXCEL ===\n")

# Read Excel file
try:
    df = pd.read_excel('2024 Players.xlsx')
    print(f"Found {len(df)} players in Excel file")
    print(f"Columns: {df.columns.tolist()}\n")

    # Show first few rows to see structure
    print("First 5 rows:")
    print(df.head())
    print("\n")

except FileNotFoundError:
    print("ERROR: 2024 Players.xlsx not found!")
    print("Please make sure the file is in the current directory.")
    exit(1)
except Exception as e:
    print(f"ERROR reading Excel: {e}")
    exit(1)

# Connect to database
conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

cur = conn.cursor(cursor_factory=RealDictCursor)

# Get team mapping from database
cur.execute("SELECT qs_team_id, abbrev, city, name FROM quick_start_teams WHERE scenario_id = 1 ORDER BY qs_team_id")
teams_db = cur.fetchall()

print(f"Teams in database ({len(teams_db)}):")
for t in teams_db[:10]:  # Show first 10
    print(f"  {t['qs_team_id']}: {t['abbrev']} - {t['city']} {t['name']}")
if len(teams_db) > 10:
    print(f"  ... and {len(teams_db) - 10} more")

# Create mapping dict (case-insensitive)
team_map = {t['abbrev'].upper(): t['qs_team_id'] for t in teams_db}

print(f"\n=== STARTING IMPORT ===")

# Clear existing players
print("\nClearing existing players...")
cur.execute("DELETE FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = 1)")
print(f"Deleted {cur.rowcount} existing players")

# Import players
print("\nImporting players from Excel...")

imported = 0
skipped = 0
errors = []

for idx, row in df.iterrows():
    try:
        # Get team
        team_abbrev = str(row.get('TEAM', '')).strip().upper()

        if not team_abbrev or pd.isna(row.get('TEAM')):
            skipped += 1
            continue

        # Map to qs_team_id
        qs_team_id = team_map.get(team_abbrev)
        if not qs_team_id:
            errors.append(f"Unknown team '{team_abbrev}' for row {idx}")
            skipped += 1
            continue

        # Parse player name
        full_name = str(row.get('NAME', '')).strip()
        if not full_name:
            skipped += 1
            continue

        # Split into first and last name
        name_parts = full_name.split()
        if len(name_parts) == 1:
            first_name = name_parts[0]
            last_name = name_parts[0]
        else:
            first_name = name_parts[0]
            last_name = ' '.join(name_parts[1:])

        # Position
        position = str(row.get('POS', 'G')).strip()[:2]

        # Age
        age = int(float(row.get('AGE', 25)))

        # Convert stats to ratings (scale 0-100)
        ppg = float(row.get('PpG', 10))
        rpg = float(row.get('RpG', 3))
        apg = float(row.get('ApG', 2))
        spg = float(row.get('SpG', 0.7))
        bpg = float(row.get('BpG', 0.5))

        ft_pct = float(row.get('FT%', 0.75))
        two_pct = float(row.get('2P%', 0.45))
        three_pct = float(row.get('3P%', 0.35))
        usg_pct = float(row.get('USG%', 20))

        # Calculate ratings (scale to 0-100)
        overall = min(99, int(40 + (ppg * 2.5) + (apg * 1.5) + (rpg * 1.2)))
        usage = min(99, int(30 + (usg_pct * 2)))
        inside = min(99, int(30 + (two_pct * 130)))
        outside = min(99, int(30 + (three_pct * 150)))
        ft = min(99, int(ft_pct * 95))
        passing = min(99, int(40 + (apg * 10)))
        speed = min(99, int(50 + (position in ['G'] and 15 or 0)))  # Guards faster
        guarding = min(99, int(40 + (spg * 25)))
        stealing = min(99, int(40 + (spg * 30)))
        blocking = min(99, int(30 + (bpg * 35)))
        rebounding = min(99, int(30 + (rpg * 8)))

        # Estimate contract based on overall rating
        if overall >= 90:
            salary = 40000000 + (overall - 90) * 2000000
            contract_years = 4
        elif overall >= 85:
            salary = 25000000 + (overall - 85) * 3000000
            contract_years = 3
        elif overall >= 80:
            salary = 15000000 + (overall - 80) * 2000000
            contract_years = 3
        elif overall >= 75:
            salary = 8000000 + (overall - 75) * 1400000
            contract_years = 2
        elif overall >= 70:
            salary = 3000000 + (overall - 70) * 1000000
            contract_years = 2
        else:
            salary = 1500000 + (overall - 60) * 150000
            contract_years = 1

        salary = int(salary)

        # Insert into database
        cur.execute("""
            INSERT INTO quick_start_players
            (qs_team_id, first_name, last_name, position, age, usage_rating,
             inside_shooting, outside_shooting, ft_shooting, passing, speed,
             guarding, stealing, blocking, rebounding, overall_rating,
             contract_years, salary_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (qs_team_id, first_name, last_name, position, age, usage,
              inside, outside, ft, passing, speed, guarding, stealing,
              blocking, rebounding, overall, contract_years, salary))

        imported += 1

        if imported % 50 == 0:
            print(f"  Imported {imported} players...")

    except Exception as e:
        errors.append(f"Row {idx}: {str(e)}")
        skipped += 1

# Commit changes
conn.commit()

# Summary
print(f"\n=== IMPORT COMPLETE ===")
print(f"Imported: {imported} players")
print(f"Skipped: {skipped} rows")

if errors:
    print(f"\nErrors ({len(errors)} total):")
    for err in errors[:10]:  # Show first 10 errors
        print(f"  - {err}")
    if len(errors) > 10:
        print(f"  ... and {len(errors) - 10} more errors")

# Verify
cur.execute("SELECT COUNT(*) as count FROM quick_start_players")
total = cur.fetchone()['count']
print(f"\nTotal players in database: {total}")

cur.execute("""
    SELECT t.abbrev, t.city, t.name, COUNT(p.player_id) as player_count
    FROM quick_start_teams t
    LEFT JOIN quick_start_players p ON t.qs_team_id = p.qs_team_id
    WHERE t.scenario_id = 1
    GROUP BY t.qs_team_id
    ORDER BY player_count DESC
    LIMIT 10
""")

print("\nPlayers per team (top 10):")
for row in cur.fetchall():
    print(f"  {row['abbrev']}: {row['player_count']} players")

conn.close()

print("\nDone! Your database now has real NBA rosters.")
