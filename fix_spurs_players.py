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

print("=== FIXING SPURS PLAYERS ===\n")

# Known Spurs players (2024-25 roster)
spurs_players = [
    'Wembanyama', 'Vassell', 'Sochan', 'Johnson', 'Champagnie',
    'Barnes', 'Castle', 'Jones', 'Wesley', 'Branham',
    'Collins', 'Paul', 'Osman', 'Risacher' # Add more as needed
]

# Get SA and SAC team IDs from quick_start
cur.execute("SELECT qs_team_id, abbrev FROM quick_start_teams WHERE abbrev IN ('SA', 'SAC') AND scenario_id = 1")
teams = {row['abbrev']: row['qs_team_id'] for row in cur.fetchall()}

sa_team_id = teams.get('SA')
sac_team_id = teams.get('SAC')

print(f"San Antonio (SA) team ID: {sa_team_id}")
print(f"Sacramento (SAC) team ID: {sac_team_id}")

# Find Spurs players currently assigned to SAC
moved = 0
for player_name in spurs_players:
    cur.execute("""
        UPDATE quick_start_players
        SET qs_team_id = %s
        WHERE qs_team_id = %s
          AND (last_name ILIKE %s OR first_name ILIKE %s)
    """, (sa_team_id, sac_team_id, f'%{player_name}%', f'%{player_name}%'))

    if cur.rowcount > 0:
        print(f"  Moved {cur.rowcount} player(s) matching '{player_name}' to Spurs")
        moved += cur.rowcount

conn.commit()

print(f"\nTotal players moved: {moved}")

# Verify
cur.execute("SELECT COUNT(*) as count FROM quick_start_players WHERE qs_team_id = %s", (sa_team_id,))
sa_count = cur.fetchone()['count']

cur.execute("SELECT COUNT(*) as count FROM quick_start_players WHERE qs_team_id = %s", (sac_team_id,))
sac_count = cur.fetchone()['count']

print(f"\nSan Antonio Spurs: {sa_count} players")
print(f"Sacramento Kings: {sac_count} players")

# Also need to fix any existing leagues
print("\nFixing existing leagues...")
cur.execute("SELECT league_id, name FROM leagues")
leagues = cur.fetchall()

for league in leagues:
    league_id = league['league_id']

    # Get team IDs in this league
    cur.execute("SELECT team_id, abbrev FROM league_teams WHERE league_id = %s AND abbrev IN ('SA', 'SAC')", (league_id,))
    league_teams = {row['abbrev']: row['team_id'] for row in cur.fetchall()}

    if 'SA' not in league_teams or 'SAC' not in league_teams:
        continue

    sa_league_team_id = league_teams['SA']
    sac_league_team_id = league_teams['SAC']

    moved_league = 0
    for player_name in spurs_players:
        cur.execute("""
            UPDATE league_players
            SET team_id = %s
            WHERE team_id = %s
              AND league_id = %s
              AND (last_name ILIKE %s OR first_name ILIKE %s)
        """, (sa_league_team_id, sac_league_team_id, league_id, f'%{player_name}%', f'%{player_name}%'))

        moved_league += cur.rowcount

    if moved_league > 0:
        print(f"  League '{league['name']}': Moved {moved_league} players to Spurs")

conn.commit()
conn.close()

print("\nDone! Spurs should now have their players.")
