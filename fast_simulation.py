import random
import json
from psycopg2.extras import RealDictCursor

def run_fast_game_simulation(conn, league_id, game_id, home_team_id, away_team_id):
    """
    Fast simulation that generates realistic stats without possession-by-possession detail.
    10-20x faster than full simulation.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # ---------------------------------------------------------
    # 1. FETCH PLAYERS
    # ---------------------------------------------------------
    cur.execute("""
        SELECT * FROM league_players
        WHERE team_id IN (%s, %s) AND league_id = %s
        ORDER BY overall_rating DESC
    """, (home_team_id, away_team_id, league_id))
    all_players = cur.fetchall()

    rosters = {home_team_id: [], away_team_id: []}
    for p in all_players:
        rosters[p['team_id']].append(p)

    # ---------------------------------------------------------
    # 2. CALCULATE TEAM RATINGS
    # ---------------------------------------------------------
    def get_team_rating(roster):
        """Calculate overall team strength"""
        if not roster:
            return 70
        # Weight by top 8 players (rotation)
        top_players = roster[:8]
        return sum(p['overall_rating'] for p in top_players) / len(top_players)

    home_rating = get_team_rating(rosters[home_team_id])
    away_rating = get_team_rating(rosters[away_team_id])

    # Home court advantage
    home_rating += 3

    # ---------------------------------------------------------
    # 3. GENERATE FINAL SCORE
    # ---------------------------------------------------------
    # Base score around 105-115 range
    base_score = 110
    rating_factor = 0.4  # How much rating affects score

    home_score = int(base_score + (home_rating - 75) * rating_factor + random.randint(-8, 8))
    away_score = int(base_score + (away_rating - 75) * rating_factor + random.randint(-8, 8))

    # Ensure home score is slightly higher on average
    if random.random() < 0.52:  # 52% home win rate
        home_score = max(home_score, away_score + random.randint(1, 5))

    # Clamp scores to reasonable range
    home_score = max(85, min(135, home_score))
    away_score = max(85, min(135, away_score))

    # Quarter scores (roughly distributed)
    def distribute_quarters(total_score):
        q1 = int(total_score * random.uniform(0.22, 0.28))
        q2 = int(total_score * random.uniform(0.22, 0.28))
        q3 = int(total_score * random.uniform(0.22, 0.28))
        q4 = total_score - q1 - q2 - q3
        return [q1, q2, q3, q4]

    home_quarters = distribute_quarters(home_score)
    away_quarters = distribute_quarters(away_score)

    # ---------------------------------------------------------
    # 4. GENERATE PLAYER STATS
    # ---------------------------------------------------------
    def generate_player_stats(roster, team_score, team_id):
        """Distribute team stats to players based on ratings"""
        if not roster:
            return []

        stats_list = []
        remaining_points = team_score

        # Sort by overall rating
        players = sorted(roster, key=lambda x: x['overall_rating'], reverse=True)

        for i, p in enumerate(players[:10]):  # Top 10 players get minutes
            # Minutes distribution (starters get more)
            if i < 5:  # Starters
                minutes = random.randint(32, 38)
            elif i < 8:  # Bench
                minutes = random.randint(15, 25)
            else:  # Deep bench
                minutes = random.randint(5, 15)

            # Points based on rating and usage
            usage_factor = p['usage_rating'] / 100.0
            rating_factor = p['overall_rating'] / 80.0

            if i == 0:  # Star player
                points = int(team_score * random.uniform(0.20, 0.30))
            elif i < 3:  # Key players
                points = int(team_score * random.uniform(0.12, 0.20))
            elif i < 5:  # Starters
                points = int(team_score * random.uniform(0.05, 0.12))
            else:  # Bench
                points = int(team_score * random.uniform(0.02, 0.08))

            remaining_points -= points

            # Generate other stats based on position and ratings
            # Rebounds
            if p['position'] in ['C', 'PF']:
                rebounds = int(minutes * random.uniform(0.25, 0.40))
            elif p['position'] == 'SF':
                rebounds = int(minutes * random.uniform(0.15, 0.25))
            else:
                rebounds = int(minutes * random.uniform(0.08, 0.15))

            # Assists
            if p['position'] == 'PG':
                assists = int(minutes * random.uniform(0.15, 0.30))
            elif p['position'] in ['SG', 'SF']:
                assists = int(minutes * random.uniform(0.08, 0.15))
            else:
                assists = int(minutes * random.uniform(0.03, 0.10))

            # Shooting stats
            fg_attempts = int(points * random.uniform(0.8, 1.2))
            fg_made = int(fg_attempts * (p['inside_shooting'] + p['outside_shooting']) / 200.0)

            threes_attempts = int(fg_attempts * (p['outside_shooting'] / 150.0))
            threes_made = int(threes_attempts * random.uniform(0.30, 0.45))

            ft_attempts = int(points * random.uniform(0.15, 0.30))
            ft_made = int(ft_attempts * (p['ft_shooting'] / 100.0))

            stats_list.append({
                'player_id': p['player_id'],
                'team_id': team_id,
                'minutes': minutes,
                'points': max(0, points),
                'rebounds': max(0, rebounds),
                'assists': max(0, assists),
                'fg_made': max(0, fg_made),
                'fg_attempts': max(0, fg_attempts),
                'threes_made': max(0, threes_made),
                'threes_attempts': max(0, threes_attempts),
                'ft_made': max(0, ft_made),
                'ft_attempts': max(0, ft_attempts),
                'fouls': random.randint(0, 5)
            })

        return stats_list

    home_stats = generate_player_stats(rosters[home_team_id], home_score, home_team_id)
    away_stats = generate_player_stats(rosters[away_team_id], away_score, away_team_id)

    # ---------------------------------------------------------
    # 5. SAVE TO DATABASE
    # ---------------------------------------------------------

    # Update game result
    cur.execute("""
        UPDATE league_schedule
        SET home_score=%s, away_score=%s, is_played=TRUE,
            home_q1=%s, home_q2=%s, home_q3=%s, home_q4=%s,
            away_q1=%s, away_q2=%s, away_q3=%s, away_q4=%s
        WHERE game_id=%s
    """, (home_score, away_score,
          home_quarters[0], home_quarters[1], home_quarters[2], home_quarters[3],
          away_quarters[0], away_quarters[1], away_quarters[2], away_quarters[3],
          game_id))

    # Insert box scores (bulk)
    all_stats = home_stats + away_stats
    if all_stats:
        box_score_data = []
        for s in all_stats:
            box_score_data.append((
                league_id, game_id, s['team_id'], s['player_id'], s['minutes'],
                s['points'], s['rebounds'], s['assists'], s['fg_made'], s['fg_attempts'],
                s['threes_made'], s['threes_attempts'], s['ft_made'], s['ft_attempts'], s['fouls']
            ))

        args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", x).decode('utf-8') for x in box_score_data)
        cur.execute("INSERT INTO league_box_scores (league_id, game_id, team_id, player_id, minutes, points, rebounds, assists, fg_made, fg_attempts, threes_made, threes_attempts, ft_made, ft_attempts, fouls) VALUES " + args_str)

    # Update standings
    winner = home_team_id if home_score > away_score else away_team_id
    loser = away_team_id if winner == home_team_id else home_team_id

    cur.execute("""
        UPDATE league_teams
        SET wins = wins + 1,
            streak_length = CASE WHEN streak_type='W' THEN streak_length + 1 ELSE 1 END,
            streak_type = 'W'
        WHERE team_id = %s
    """, (winner,))

    cur.execute("""
        UPDATE league_teams
        SET losses = losses + 1,
            streak_length = CASE WHEN streak_type='L' THEN streak_length + 1 ELSE 1 END,
            streak_type = 'L'
        WHERE team_id = %s
    """, (loser,))

    conn.commit()
    cur.close()
