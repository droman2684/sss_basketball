from dotenv import load_dotenv
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def reassign_league_contracts(conn, league_id):
    """
    Redistribute player salaries to fit under the salary cap.
    Salaries are assigned based on overall rating.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get salary cap for this league
    cur.execute("SELECT salary_cap FROM leagues WHERE league_id = %s", (league_id,))
    result = cur.fetchone()
    if not result:
        return {'success': False, 'error': 'League not found'}

    salary_cap = result['salary_cap']

    # Get all teams in the league
    cur.execute("SELECT team_id FROM league_teams WHERE league_id = %s", (league_id,))
    teams = cur.fetchall()

    teams_updated = 0
    total_players_updated = 0

    for team in teams:
        team_id = team['team_id']

        # Get all players on this team, sorted by overall rating
        cur.execute("""
            SELECT player_id, overall_rating
            FROM league_players
            WHERE team_id = %s AND league_id = %s
            ORDER BY overall_rating DESC
        """, (team_id, league_id))

        players = cur.fetchall()
        if not players:
            continue

        # Calculate salary distribution
        # Total "points" = sum of all overall ratings
        total_rating_points = sum(p['overall_rating'] for p in players)

        # Distribute cap space proportionally with scaling
        for player in players:
            rating = player['overall_rating']

            # Base salary from proportional distribution
            base_share = (rating / total_rating_points) * salary_cap

            # Apply scaling curve to make stars earn more
            # This creates a more realistic NBA salary structure
            if rating >= 90:  # Superstar
                salary_multiplier = 1.8
                min_salary = 35000000
            elif rating >= 85:  # All-Star
                salary_multiplier = 1.5
                min_salary = 25000000
            elif rating >= 80:  # Starter
                salary_multiplier = 1.2
                min_salary = 15000000
            elif rating >= 75:  # Good role player
                salary_multiplier = 1.0
                min_salary = 8000000
            elif rating >= 70:  # Role player
                salary_multiplier = 0.8
                min_salary = 4000000
            else:  # Bench
                salary_multiplier = 0.6
                min_salary = 1500000

            new_salary = int(max(min_salary, base_share * salary_multiplier))

            # Contract length based on age and rating
            cur.execute("SELECT age FROM league_players WHERE player_id = %s", (player['player_id'],))
            age = cur.fetchone()['age']

            if rating >= 85 and age < 30:
                contract_years = 4
            elif rating >= 80:
                contract_years = 3
            elif rating >= 70:
                contract_years = 2
            else:
                contract_years = 1

            # Update player contract
            cur.execute("""
                UPDATE league_players
                SET salary_amount = %s, contract_years = %s
                WHERE player_id = %s
            """, (new_salary, contract_years, player['player_id']))

            total_players_updated += 1

        teams_updated += 1

    conn.commit()
    cur.close()

    return {
        'success': True,
        'teams_updated': teams_updated,
        'players_updated': total_players_updated,
        'salary_cap': salary_cap
    }


if __name__ == '__main__':
    # Test script
    load_dotenv()

    conn = psycopg2.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        host=os.getenv('DB_HOST'),
        sslmode='require'
    )

    # Get most recent league
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC LIMIT 1")
    league = cur.fetchone()

    if league:
        print(f"Reassigning contracts for: {league['name']}")
        result = reassign_league_contracts(conn, league['league_id'])

        if result['success']:
            print(f"Success!")
            print(f"  Teams updated: {result['teams_updated']}")
            print(f"  Players updated: {result['players_updated']}")
            print(f"  Salary cap: ${result['salary_cap']:,}")
        else:
            print(f"Error: {result.get('error')}")
    else:
        print("No leagues found")

    conn.close()
