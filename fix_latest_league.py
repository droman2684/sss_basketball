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

print("=== FIX LATEST LEAGUE ===\n")

# Get most recent league
cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC LIMIT 1")
league = cur.fetchone()

if not league:
    print("No leagues found!")
    exit(0)

league_id = league['league_id']
print(f"League: {league['name']} (ID: {league_id})")

# Check current player count
cur.execute("SELECT COUNT(*) as count FROM league_players WHERE league_id = %s", (league_id,))
current_count = cur.fetchone()['count']
print(f"Current players in league: {current_count}")

if current_count > 0:
    print("\nLeague already has players!")
    print("If you want to repopulate, first delete them:")
    print(f"  DELETE FROM league_players WHERE league_id = {league_id};")
    exit(0)

print("\nPopulating league with players...")

# Get teams in this league
cur.execute("SELECT team_id, abbrev FROM league_teams WHERE league_id = %s", (league_id,))
league_teams = {t['abbrev'].upper(): t['team_id'] for t in cur.fetchall()}
print(f"Teams in league: {len(league_teams)}")

# Get all quick start players
cur.execute("""
    SELECT p.*, t.abbrev
    FROM quick_start_players p
    JOIN quick_start_teams t ON p.qs_team_id = t.qs_team_id
    WHERE t.scenario_id = 1
""")
qs_players = cur.fetchall()
print(f"Available players: {len(qs_players)}")

imported = 0
for p in qs_players:
    abbrev = p['abbrev'].upper()
    league_team_id = league_teams.get(abbrev)

    if not league_team_id:
        continue

    cur.execute("""
        INSERT INTO league_players
        (team_id, league_id, first_name, last_name, position, age, usage_rating,
         inside_shooting, outside_shooting, ft_shooting, passing, speed,
         guarding, stealing, blocking, rebounding, overall_rating,
         contract_years, salary_amount)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (league_team_id, league_id, p['first_name'], p['last_name'], p['position'],
          p['age'], p['usage_rating'], p['inside_shooting'], p['outside_shooting'],
          p['ft_shooting'], p['passing'], p['speed'], p['guarding'],
          p['stealing'], p['blocking'], p['rebounding'], p['overall_rating'],
          p['contract_years'], p['salary_amount']))

    imported += 1
    if imported % 50 == 0:
        print(f"  Imported {imported} players...")

conn.commit()

print(f"\nSuccess! Imported {imported} players")

# Verify
cur.execute("SELECT COUNT(*) as count FROM league_players WHERE league_id = %s", (league_id,))
total = cur.fetchone()['count']
print(f"Total players in league now: {total}")

# Show sample
cur.execute("""
    SELECT t.abbrev, COUNT(p.player_id) as player_count
    FROM league_teams t
    LEFT JOIN league_players p ON t.team_id = p.team_id
    WHERE t.league_id = %s
    GROUP BY t.abbrev
    ORDER BY player_count DESC
    LIMIT 10
""")
print("\nPlayers per team (top 10):")
for row in cur.fetchall():
    print(f"  {row['abbrev']}: {row['player_count']} players")

conn.close()
print("\nDone! Your league is now ready to simulate!")
