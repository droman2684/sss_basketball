import random
import json
from psycopg2.extras import RealDictCursor

def run_game_simulation(conn, league_id, game_id, home_team_id, away_team_id):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # ---------------------------------------------------------
    # 1. FETCH PLAYERS & STRATEGIES
    # ---------------------------------------------------------
    
    # Fetch Players
    cur.execute("""
        SELECT * FROM league_players 
        WHERE team_id IN (%s, %s) AND league_id = %s
        ORDER BY overall_rating DESC
    """, (home_team_id, away_team_id, league_id))
    all_players = cur.fetchall()
    
    # Fetch Coaching Strategies
    cur.execute("""
        SELECT * FROM coaching_strategy 
        WHERE team_id IN (%s, %s)
    """, (home_team_id, away_team_id))
    strategies_db = cur.fetchall()
    
    # Organize Rosters
    rosters = {home_team_id: [], away_team_id: []}
    for p in all_players:
        # Initialize stat tracking
        p['stats'] = {k: 0 for k in ['pts','reb','ast','stl','blk','to','fgm','fga','3pm','3pa','ftm','fta','min','pf']}
        rosters[p['team_id']].append(p)

    # Organize Strategies (Default if missing)
    team_strategies = {}
    default_strat = {
        'offense_focus': 'balanced', 
        'defense_focus': 'balanced', 
        'bench_minutes': 'normal'
    }
    
    # Fill dictionary with DB results
    for s in strategies_db:
        team_strategies[s['team_id']] = s
        
    # Ensure both teams have a strategy object
    for tid in [home_team_id, away_team_id]:
        if tid not in team_strategies:
            team_strategies[tid] = default_strat

    # Track disqualified players
    disqualified = {home_team_id: [], away_team_id: []}

    # ---------------------------------------------------------
    # 2. SMART ROTATION LOGIC (With Strategy)
    # ---------------------------------------------------------
    def get_lineup(team_id, quarter, minute_remaining):
        team_roster = rosters[team_id]
        strat = team_strategies[team_id].get('bench_minutes', 'normal')
        
        # Filter disqualified
        available = [p for p in team_roster if p['player_id'] not in disqualified[team_id]]
        
        # Define Rotation Depth
        starters = available[:5]
        bench = available[5:10] if len(available) >= 10 else available[5:]
        
        # Emergency: If bench depleted by fouls
        if len(bench) < 5:
            needed = 5 - len(bench)
            bench += starters[:needed]

        # --- APPLY ROTATION STRATEGY ---
        # "Normal": Starters play Q1/Q3. Bench plays first 6 mins of Q2/Q4.
        # "Heavy": Starters play ~42 mins. Bench only plays first 3 mins of Q2/Q4.
        # "Deep": Bench plays longer stretches (e.g., first 8 mins of Q2/Q4).
        
        bench_limit_minute = 6.0 # Default (Bench plays 12:00 to 6:00)
        
        if strat == 'heavy':
            bench_limit_minute = 9.0 # Bench plays 12:00 to 9:00 (3 mins)
        elif strat == 'deep' or strat == 'load_manage':
            bench_limit_minute = 4.0 # Bench plays 12:00 to 4:00 (8 mins)

        # Logic: Q1/Q3 are starters. Q2/Q4 vary based on strategy.
        if quarter in [1, 3]:
            return starters
        elif quarter in [2, 4]:
            # If time remaining > limit, Bench is in. Else, Starters close.
            if minute_remaining > bench_limit_minute:
                return bench
            else:
                return starters
        
        return starters

    # Game State
    score = {home_team_id: 0, away_team_id: 0}
    quarter_scores = {home_team_id: [0,0,0,0], away_team_id: [0,0,0,0]}
    game_log = []
    win_prob_log = []
    
    # ---------------------------------------------------------
    # 3. GAME LOOP
    # ---------------------------------------------------------
    for q in range(1, 5):
        time_remaining = 720 # 12 mins in seconds
        
        while time_remaining > 0:
            # Update minute decimal for rotation check
            minute_dec = time_remaining / 60.0
            
            home5 = get_lineup(home_team_id, q, minute_dec)
            away5 = get_lineup(away_team_id, q, minute_dec)
            
            # Determine Offense/Defense
            if random.random() > 0.5:
                offense_team, defense_team = home5, away5
                off_id, def_id = home_team_id, away_team_id
            else:
                offense_team, defense_team = away5, home5
                off_id, def_id = away_team_id, home_team_id

            # Get Strategies for current possession
            off_strat = team_strategies[off_id]
            def_strat = team_strategies[def_id]

            # --- A. PACE MODIFIER ---
            # Default possession 12-24s.
            # Pace = Faster (10-18s). Slow = Slower (16-24s).
            min_pace, max_pace = 12, 24
            
            if off_strat['offense_focus'] == 'pace':
                min_pace, max_pace = 8, 18
            elif off_strat['offense_focus'] == 'slow':
                min_pace, max_pace = 16, 24
                
            possession_time = random.randint(min_pace, max_pace)
            
            # Track Minutes
            for p in home5 + away5:
                p['stats']['min'] += possession_time / 60.0

            # --- B. SELECT SHOOTER ---
            # Standard weighted choice by usage
            total_usage = sum(p['usage_rating'] for p in offense_team)
            r = random.uniform(0, total_usage)
            current = 0
            shooter = offense_team[0]
            for p in offense_team:
                current += p['usage_rating']
                if r <= current:
                    shooter = p
                    break
            
            defender = random.choice(defense_team)
            
            # --- C. FOUL LOGIC ---
            # Pressure defense causes more fouls
            foul_chance = 15 + (100 - defender['guarding']) * 0.1
            if def_strat['defense_focus'] == 'pressure':
                foul_chance += 8 # Aggressive defense fouls more
            
            is_foul = random.uniform(0, 100) < foul_chance

            # --- D. SHOT TYPE (3PT vs 2PT) ---
            # Base logic: Rating / 200. e.g. 80 rating -> 40% chance to take 3
            base_three_prob = (shooter['outside_shooting'] / 200.0)
            
            # Apply Strategy Modifiers
            if off_strat['offense_focus'] == '3pt':
                base_three_prob += 0.20 # Huge boost to 3PA
            elif off_strat['offense_focus'] == 'paint':
                base_three_prob -= 0.15 # Focus on rim

            is_three = random.random() < base_three_prob
            shot_val = 3 if is_three else 2
            
            # --- E. SHOT SUCCESS CALCULATION ---
            shot_rating = (shooter['outside_shooting'] if is_three else shooter['inside_shooting'])
            defense_rating = defender['guarding']
            
            # Strategy: Defense Bonuses
            if def_strat['defense_focus'] == 'paint' and not is_three:
                defense_rating += 15 # Bonus vs 2pt
            elif def_strat['defense_focus'] == 'perimeter' and is_three:
                defense_rating += 15 # Bonus vs 3pt
            
            defense_impact = defense_rating * 0.5
            hit_threshold = 45 + (shot_rating - defense_impact) * 0.2
            
            # Strategy: Offense Bonuses (Paint focus = higher % on 2s)
            if off_strat['offense_focus'] == 'paint' and not is_three:
                hit_threshold += 5 
                
            shot_roll = random.uniform(0, 100)
            is_made = shot_roll < hit_threshold

            event_desc = ""

            if is_foul:
                # RECORD FOUL
                defender['stats']['pf'] += 1
                
                # Check Foul Out
                if defender['stats']['pf'] >= 6:
                    disqualified[def_id].append(defender['player_id'])
                    game_log.append({
                        'game_id': game_id, 'quarter': q, 'time': f"{int(time_remaining//60)}:{int(time_remaining%60):02d}",
                        'desc': f"{defender['last_name']} fouled out (6 PF)", 'h_score': score[home_team_id], 'a_score': score[away_team_id], 'type': 'FOUL'
                    })

                # SHOOTING FOUL LOGIC
                ft_attempts = 0
                if is_made:
                    # And-1
                    shooter['stats']['pts'] += shot_val
                    shooter['stats']['fgm'] += 1
                    shooter['stats']['fga'] += 1
                    if is_three: 
                        shooter['stats']['3pm'] += 1
                        shooter['stats']['3pa'] += 1
                    
                    score[off_id] += shot_val
                    quarter_scores[off_id][q-1] += shot_val
                    event_desc = f"{shooter['last_name']} made shot AND fouled by {defender['last_name']}!"
                    ft_attempts = 1
                else:
                    # Missed shot
                    shooter['stats']['fga'] += 1
                    if is_three: shooter['stats']['3pa'] += 1
                    event_desc = f"{shooter['last_name']} fouled by {defender['last_name']} on shot."
                    ft_attempts = 3 if is_three else 2

                # PROCESS FTs
                made_fts = 0
                for _ in range(ft_attempts):
                    shooter['stats']['fta'] += 1
                    if random.uniform(0, 100) < shooter['ft_shooting']:
                        shooter['stats']['ftm'] += 1
                        shooter['stats']['pts'] += 1
                        score[off_id] += 1
                        quarter_scores[off_id][q-1] += 1
                        made_fts += 1
                
                event_desc += f" (FT: {made_fts}/{ft_attempts})"

            else:
                # NORMAL SHOT
                if is_made:
                    shooter['stats']['pts'] += shot_val
                    shooter['stats']['fgm'] += 1
                    shooter['stats']['fga'] += 1
                    if is_three:
                        shooter['stats']['3pm'] += 1
                        shooter['stats']['3pa'] += 1
                    score[off_id] += shot_val
                    quarter_scores[off_id][q-1] += shot_val
                    event_desc = f"{shooter['last_name']} made {shot_val}pt shot"
                    
                    # Assist Logic
                    if random.random() < 0.6:
                        passer = random.choice([p for p in offense_team if p != shooter])
                        # Playmaking strategy bonus
                        pass_rating = passer['passing']
                        if off_strat.get('training_focus') == 'playmaking': pass_rating += 5
                        
                        if random.uniform(0, 100) < pass_rating:
                            passer['stats']['ast'] += 1
                            event_desc += f" (Ast: {passer['last_name']})"
                else:
                    shooter['stats']['fga'] += 1
                    if is_three: shooter['stats']['3pa'] += 1
                    event_desc = f"{shooter['last_name']} missed shot"
                    
                    # Rebound Logic
                    all_on_court = home5 + away5
                    total_reb = sum(p['rebounding'] for p in all_on_court)
                    r_reb = random.uniform(0, total_reb)
                    curr_reb = 0
                    rebounder = all_on_court[0]
                    for p in all_on_court:
                        curr_reb += p['rebounding']
                        if r_reb <= curr_reb:
                            rebounder = p
                            break
                    rebounder['stats']['reb'] += 1

            # Decrease Clock
            time_remaining -= possession_time
            
            # Log Event (only important plays to speed up simulation)
            is_important = (is_made and shot_val >= 2) or is_foul or (abs(score[home_team_id] - score[away_team_id]) <= 5 and time_remaining < 120)
            if is_important or len(game_log) < 10:  # Always log first 10 events + important plays
                game_log.append({
                    'game_id': game_id,
                    'quarter': q,
                    'time': f"{int(time_remaining//60)}:{int(time_remaining%60):02d}",
                    'desc': event_desc,
                    'h_score': score[home_team_id],
                    'a_score': score[away_team_id],
                    'type': 'SHOT'
                })

            # Win Prob Graph
            if int(time_remaining) % 60 < 20: 
                diff = score[home_team_id] - score[away_team_id]
                t_factor = 2000 / (((4-q)*720 + time_remaining) + 100)
                prob = 1 / (1 + 2.718 ** -(diff * 0.1 * (t_factor/5)))
                win_prob_log.append(round(prob * 100, 1))

    # ---------------------------------------------------------
    # 4. SAVE RESULTS TO DB
    # ---------------------------------------------------------
    
    # Update Schedule
    cur.execute("""
        UPDATE league_schedule 
        SET home_score=%s, away_score=%s, is_played=TRUE,
            home_q1=%s, home_q2=%s, home_q3=%s, home_q4=%s,
            away_q1=%s, away_q2=%s, away_q3=%s, away_q4=%s,
            win_prob_history=%s
        WHERE game_id=%s
    """, (score[home_team_id], score[away_team_id], 
          quarter_scores[home_team_id][0], quarter_scores[home_team_id][1], quarter_scores[home_team_id][2], quarter_scores[home_team_id][3],
          quarter_scores[away_team_id][0], quarter_scores[away_team_id][1], quarter_scores[away_team_id][2], quarter_scores[away_team_id][3],
          json.dumps(win_prob_log), game_id))

    # Insert Box Scores (Bulk Insert for Speed)
    box_score_data = []
    for team_id in [home_team_id, away_team_id]:
        for p in rosters[team_id]:
            s = p['stats']
            if s['min'] > 0:
                box_score_data.append((league_id, game_id, team_id, p['player_id'], int(s['min']),
                                      s['pts'], s['reb'], s['ast'], s['fgm'], s['fga'],
                                      s['3pm'], s['3pa'], s['ftm'], s['fta'], s['pf']))

    if box_score_data:
        args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", x).decode('utf-8') for x in box_score_data)
        cur.execute("INSERT INTO league_box_scores (league_id, game_id, team_id, player_id, minutes, points, rebounds, assists, fg_made, fg_attempts, threes_made, threes_attempts, ft_made, ft_attempts, fouls) VALUES " + args_str)

    # Insert Game Events (Bulk Insert)
    if game_log:
        args_list = [(l['game_id'], l['quarter'], l['time'], l['desc'], l['h_score'], l['a_score'], l['type']) for l in game_log]
        args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s)", x).decode('utf-8') for x in args_list)
        cur.execute("INSERT INTO league_game_events (game_id, quarter, time_remaining, description, score_home, score_away, event_type) VALUES " + args_str)

    # Update Standings / Streaks
    winner = home_team_id if score[home_team_id] > score[away_team_id] else away_team_id
    loser = away_team_id if winner == home_team_id else home_team_id
    
    # Update Winner
    cur.execute("""
        UPDATE league_teams 
        SET wins = wins + 1, 
            streak_length = CASE WHEN streak_type='W' THEN streak_length + 1 ELSE 1 END,
            streak_type = 'W'
        WHERE team_id = %s
    """, (winner,))
    
    # Update Loser
    cur.execute("""
        UPDATE league_teams 
        SET losses = losses + 1, 
            streak_length = CASE WHEN streak_type='L' THEN streak_length + 1 ELSE 1 END,
            streak_type = 'L'
        WHERE team_id = %s
    """, (loser,))
    
    conn.commit()
    cur.close()