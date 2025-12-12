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

# Get latest league
cur.execute("SELECT * FROM leagues ORDER BY created_at DESC LIMIT 1")
league = cur.fetchone()
league_id = league['league_id']
sim_date = league['sim_date']

print(f"League: {league['name']}")
print(f"Sim Date: {sim_date}")
print()

# Get today's games
cur.execute("""
    SELECT s.game_id, s.home_team_id, s.away_team_id,
           th.name as home_name, ta.name as away_name
    FROM league_schedule s
    JOIN league_teams th ON s.home_team_id = th.team_id
    JOIN league_teams ta ON s.away_team_id = ta.team_id
    WHERE s.league_id = %s
      AND s.day_of_month = EXTRACT(DAY FROM %s::date)
      AND s.year = EXTRACT(YEAR FROM %s::date)
      AND TRIM(s.month_name) = TRIM(TO_CHAR(%s::date, 'Month'))
      AND s.is_played = FALSE
""", (league_id, sim_date, sim_date, sim_date))

games = cur.fetchall()
print(f"Games scheduled for today: {len(games)}")

if games:
    for g in games:
        print(f"\nGame {g['game_id']}: {g['home_name']} vs {g['away_name']}")
        print(f"  Home Team ID: {g['home_team_id']}")
        print(f"  Away Team ID: {g['away_team_id']}")

        # Check players for each team
        cur.execute("SELECT COUNT(*) as count FROM league_players WHERE team_id = %s AND league_id = %s",
                   (g['home_team_id'], league_id))
        home_players = cur.fetchone()['count']

        cur.execute("SELECT COUNT(*) as count FROM league_players WHERE team_id = %s AND league_id = %s",
                   (g['away_team_id'], league_id))
        away_players = cur.fetchone()['count']

        print(f"  Home players: {home_players}")
        print(f"  Away players: {away_players}")

        if home_players == 0 or away_players == 0:
            print("  ERROR: Team has no players!")
else:
    print("No games scheduled for today")
    print("\nAll teams and their player counts:")
    cur.execute("""
        SELECT t.team_id, t.name, COUNT(p.player_id) as player_count
        FROM league_teams t
        LEFT JOIN league_players p ON t.team_id = p.team_id
        WHERE t.league_id = %s
        GROUP BY t.team_id
        ORDER BY player_count
    """, (league_id,))

    for row in cur.fetchall():
        print(f"  Team {row['team_id']} ({row['name']}): {row['player_count']} players")

conn.close()
