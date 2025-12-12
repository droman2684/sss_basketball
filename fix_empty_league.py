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

print("=== FIX EMPTY LEAGUE ===\n")

# Get all leagues
cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
leagues = cur.fetchall()

print("Available leagues:")
for i, league in enumerate(leagues, 1):
    cur.execute("SELECT COUNT(*) as count FROM league_players WHERE league_id = %s", (league['league_id'],))
    player_count = cur.fetchone()['count']
    print(f"{i}. League {league['league_id']}: {league['name']} ({player_count} players)")

if not leagues:
    print("No leagues found!")
    exit(0)

league_choice = input(f"\nWhich league to populate? (1-{len(leagues)}): ")
try:
    league_idx = int(league_choice) - 1
    selected_league = leagues[league_idx]
    league_id = selected_league['league_id']
except:
    print("Invalid choice!")
    exit(1)

print(f"\nPopulating league: {selected_league['name']}")

# Get teams in this league and their mapping
cur.execute("SELECT team_id, abbrev FROM league_teams WHERE league_id = %s", (league_id,))
league_teams = cur.fetchall()

print(f"Found {len(league_teams)} teams in league")

# Get quick start teams
cur.execute("SELECT qs_team_id, abbrev FROM quick_start_teams WHERE scenario_id = 1")
qs_teams = cur.fetchall()

# Create mapping: abbrev -> qs_team_id and abbrev -> team_id
qs_map = {t['abbrev'].upper(): t['qs_team_id'] for t in qs_teams}
league_map = {t['abbrev'].upper(): t['team_id'] for t in league_teams}

# Get all quick start players
cur.execute("SELECT * FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = 1)")
qs_players = cur.fetchall()

print(f"Found {len(qs_players)} players to import")

imported = 0
for p in qs_players:
    # Get the team abbrev from qs_team_id
    cur.execute("SELECT abbrev FROM quick_start_teams WHERE qs_team_id = %s", (p['qs_team_id'],))
    team_row = cur.fetchone()
    if not team_row:
        continue

    abbrev = team_row['abbrev'].upper()
    league_team_id = league_map.get(abbrev)

    if not league_team_id:
        print(f"  Warning: No team found for {abbrev}")
        continue

    # Insert player
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

print(f"\nSuccess! Imported {imported} players to league '{selected_league['name']}'")

# Verify
cur.execute("SELECT COUNT(*) as count FROM league_players WHERE league_id = %s", (league_id,))
total = cur.fetchone()['count']
print(f"Total players in league: {total}")

conn.close()
