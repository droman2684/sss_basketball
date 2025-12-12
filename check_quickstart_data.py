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

print("=== CHECKING QUICK START DATA ===\n")

# Check scenarios
cur.execute("SELECT COUNT(*) as count FROM quick_start_scenarios")
scenario_count = cur.fetchone()['count']
print(f"Quick Start Scenarios: {scenario_count}")

if scenario_count > 0:
    cur.execute("SELECT * FROM quick_start_scenarios")
    scenarios = cur.fetchall()
    for s in scenarios:
        print(f"  - Scenario {s['scenario_id']}: {s['name']}")

# Check teams
cur.execute("SELECT COUNT(*) as count FROM quick_start_teams")
team_count = cur.fetchone()['count']
print(f"\nQuick Start Teams: {team_count}")

if team_count > 0:
    cur.execute("SELECT scenario_id, COUNT(*) as count FROM quick_start_teams GROUP BY scenario_id")
    for row in cur.fetchall():
        print(f"  - Scenario {row['scenario_id']}: {row['count']} teams")

# Check players
cur.execute("SELECT COUNT(*) as count FROM quick_start_players")
player_count = cur.fetchone()['count']
print(f"\nQuick Start Players: {player_count}")

if player_count > 0:
    cur.execute("SELECT COUNT(*) as count, AVG(overall_rating) as avg_rating FROM quick_start_players")
    stats = cur.fetchone()
    print(f"  - Total: {stats['count']} players")
    print(f"  - Avg Rating: {stats['avg_rating']:.1f}")

# Check schedule
cur.execute("SELECT COUNT(*) as count FROM quick_start_schedule")
schedule_count = cur.fetchone()['count']
print(f"\nQuick Start Schedule: {schedule_count} games")

if schedule_count > 0:
    cur.execute("SELECT scenario_id, COUNT(*) as count FROM quick_start_schedule GROUP BY scenario_id")
    for row in cur.fetchall():
        print(f"  - Scenario {row['scenario_id']}: {row['count']} games")

print("\n=== SUMMARY ===")
if scenario_count == 0 or team_count == 0 or player_count == 0 or schedule_count == 0:
    print("⚠️  MISSING DATA! Quick start tables need to be populated.")
    print("These tables are used when creating a new league.")
else:
    print("✓ All quick start data is present!")

conn.close()
