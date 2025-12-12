from dotenv import load_dotenv
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd

load_dotenv()

conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

cur = conn.cursor(cursor_factory=RealDictCursor)

print("=== CHECKING TEAM ABBREVIATIONS ===\n")

# Get team abbreviations from database
cur.execute("SELECT qs_team_id, abbrev, city, name FROM quick_start_teams WHERE scenario_id = 1 ORDER BY city")
db_teams = cur.fetchall()

print("Teams in database:")
for t in db_teams:
    # Check player count
    cur.execute("SELECT COUNT(*) as count FROM quick_start_players WHERE qs_team_id = %s", (t['qs_team_id'],))
    player_count = cur.fetchone()['count']
    print(f"  {t['abbrev']:3s} - {t['city']} {t['name']:20s} ({player_count} players)")

# Read Excel to see what abbreviations are used there
print("\n\nTeam abbreviations in Excel file:")
df = pd.read_excel('2024 Players.xlsx')
team_counts = df['TEAM'].value_counts()
for team, count in team_counts.items():
    print(f"  {team}: {count} players")

# Find teams with 0 players
print("\n\nTeams with NO players:")
for t in db_teams:
    cur.execute("SELECT COUNT(*) as count FROM quick_start_players WHERE qs_team_id = %s", (t['qs_team_id'],))
    player_count = cur.fetchone()['count']
    if player_count == 0:
        print(f"  {t['abbrev']:3s} - {t['city']} {t['name']}")

conn.close()
