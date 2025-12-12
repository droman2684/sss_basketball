import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database Configuration (Same as app.py)
DB_CONFIG = {
    'dbname': os.environ.get('DB_NAME', 'basketball2026'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'Aviators2025!!'),
    'host': os.environ.get('DB_HOST', 'localhost'),
    'sslmode': 'require'
}

def archive_current_season():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    print("--- ARCHIVING SEASON HISTORY ---")

    # 1. Fetch Active League
    cur.execute("SELECT * FROM leagues ORDER BY created_at DESC LIMIT 1")
    league = cur.fetchone()
    if not league:
        print("Error: No league found.")
        return

    league_id = league['league_id']
    season_year = league['season_year']
    print(f"League Found: {league['name']} (ID: {league_id}) - Season: {season_year}")

    # 2. Find the Champion (Check Finals Series)
    cur.execute("""
        SELECT winner_team_id FROM league_playoff_series 
        WHERE league_id = %s AND round_num = 4
    """, (league_id,))
    finals = cur.fetchone()

    champion_id = None
    if finals and finals['winner_team_id']:
        champion_id = finals['winner_team_id']
        # Get Team Name for display
        cur.execute("SELECT city, name FROM league_teams WHERE team_id = %s", (champion_id,))
        champ_team = cur.fetchone()
        print(f"Champion Detected: {champ_team['city']} {champ_team['name']}")
    else:
        print("Warning: Could not automatically detect a Finals winner.")
        user_input = input("Enter the Team ID of the Champion (or press Enter to skip): ")
        if user_input.isdigit():
            champion_id = int(user_input)

    # 3. Insert Champion History
    if champion_id:
        # Check if already exists to avoid duplicates
        cur.execute("SELECT * FROM league_season_history WHERE league_id=%s AND season_year=%s", (league_id, season_year))
        if cur.fetchone():
            print("History already exists for this season. Skipping insert.")
        else:
            cur.execute("""
                INSERT INTO league_season_history (league_id, season_year, champion_team_id)
                VALUES (%s, %s, %s)
            """, (league_id, season_year, champion_id))
            print("Champion recorded successfully.")

    # 4. Snapshot Standings
    # Check if standings already exist
    cur.execute("SELECT COUNT(*) as count FROM league_standings_history WHERE league_id=%s AND season_year=%s", (league_id, season_year))
    if cur.fetchone()['count'] > 0:
        print("Standings already archived for this season.")
    else:
        print("Archiving team standings...")
        cur.execute("""
            INSERT INTO league_standings_history (league_id, season_year, team_id, wins, losses, conference, division)
            SELECT league_id, %s, team_id, wins, losses, conference, division
            FROM league_teams 
            WHERE league_id = %s
        """, (season_year, league_id))
        print("Standings archived.")

    conn.commit()
    cur.close()
    conn.close()
    print("--- ARCHIVE COMPLETE ---")

if __name__ == "__main__":
    archive_current_season()