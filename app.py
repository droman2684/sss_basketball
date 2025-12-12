from flask import Flask, request, redirect, url_for, render_template, session, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import defaultdict
import random
from simulation import run_game_simulation
from fast_simulation import run_fast_game_simulation
from reassign_contracts import reassign_league_contracts
import json
import calendar
import datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '8f42a7305491794b8865174974718299')

DB_CONFIG = {
    'dbname': os.environ.get('DB_NAME', 'basketball2026'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'Aviators2025!!'),
    'host': os.environ.get('DB_HOST', 'localhost'),
    'sslmode': 'require'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================

def calculate_gb(leader_wins, leader_losses, team_wins, team_losses):
    if leader_wins is None: return 0
    diff = ((leader_wins - team_wins) + (team_losses - leader_losses)) / 2
    return diff if diff > 0 else 0

def calculate_playoff_odds(teams):
    for t in teams:
        games_played = t['wins'] + t['losses']
        games_remaining = 82 - games_played
        win_pct = t['wins'] / games_played if games_played > 0 else 0.3
        t['projected_wins'] = t['wins'] + (games_remaining * win_pct)

    sorted_teams = sorted(teams, key=lambda x: x['projected_wins'], reverse=True)
    cutoff_wins = sorted_teams[9]['projected_wins'] if len(sorted_teams) >= 10 else 35

    for t in teams:
        diff = t['projected_wins'] - cutoff_wins
        if diff >= 5: t['playoff_odds'] = 99.9
        elif diff >= 2: t['playoff_odds'] = 80 + (diff * 5)
        elif diff >= 0: t['playoff_odds'] = 50 + (diff * 10)
        elif diff > -5: t['playoff_odds'] = 50 - (abs(diff) * 10)
        else: t['playoff_odds'] = 0.1
        
        if t['wins'] > 46: t['playoff_odds'] = 100
        if t['losses'] > 50: t['playoff_odds'] = 0
        
        t['playoff_odds'] = "{:.1f}%".format(t['playoff_odds'])
    return teams

def get_team_logo(abbrev):
    abbrev = abbrev.upper().strip()
    mapping = {
        'UT': 'utah', 'UTA': 'utah', 'UTAH': 'utah',
        'BK': 'bkn', 'BKN': 'bkn', 'NETS': 'bkn', 'NJ': 'bkn',
        'OKL': 'okc', 'OKC': 'okc', 'THUNDER': 'okc',
        'NO': 'no', 'NOP': 'no', 'PELICANS': 'no', 'NOH': 'no',
        'GS': 'gsw', 'GSW': 'gsw', 'NY': 'nyk', 'NYK': 'nyk',
        'SA': 'sas', 'SAS': 'sas', 'PHX': 'phx', 'PHO': 'phx',
        'WAS': 'was', 'WSH': 'was',
    }
    code = mapping.get(abbrev, abbrev.lower())
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{code}.png"

def record_season_history(conn, league_id, season_year, champion_id):
    """Snapshots the season stats and champion when the finals end."""
    cur = conn.cursor()
    
    # 1. Record Champion
    cur.execute("""
        INSERT INTO league_season_history (league_id, season_year, champion_team_id)
        VALUES (%s, %s, %s)
    """, (league_id, season_year, champion_id))
    
    # 2. Snapshot Standings
    cur.execute("""
        INSERT INTO league_standings_history (league_id, season_year, team_id, wins, losses, conference, division)
        SELECT league_id, %s, team_id, wins, losses, conference, division
        FROM league_teams 
        WHERE league_id = %s
    """, (season_year, league_id))
    
    conn.commit()

# --- FINANCIAL & TRADE HELPERS ---

def calculate_cap_space(conn, team_id, salary_cap):
    """Calculates used salary and remaining space"""
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(salary_amount), 0) FROM league_players WHERE team_id = %s", (team_id,))
    used_cap = float(cur.fetchone()[0])
    return max(0, salary_cap - used_cap), used_cap

def get_player_asking_price(player):
    """Determines what a player wants based on rating"""
    ovr = player['overall_rating']
    age = player['age']
    
    if ovr >= 90: base = 45000000
    elif ovr >= 85: base = 30000000
    elif ovr >= 80: base = 20000000
    elif ovr >= 75: base = 12000000
    elif ovr >= 70: base = 5000000
    else: base = 1500000 # Minimum
    
    if age < 24: base *= 1.1
    if age > 33: base *= 0.8
    
    return int(base)

def get_player_trade_value(player):
    ovr = player['overall_rating']
    age = player['age']
    contract_yrs = player['contract_years']
    value = ovr
    
    if age < 24: value += 5
    if age > 32: value -= (age - 32) * 2
    if contract_yrs > 2 and age > 30: value -= 5
    
    if ovr >= 90: value *= 1.5 
    elif ovr >= 85: value *= 1.2
    
    status = player.get('trade_status', 'yellow')
    if status == 'green': value *= 0.85
    elif status == 'red': value *= 2.5
    
    return int(value)

def get_pick_trade_value(pick, team_record):
    win_pct = team_record['wins'] / (team_record['wins'] + team_record['losses']) if (team_record['wins'] + team_record['losses']) > 0 else 0.5
    projected_rank = 100 - (win_pct * 100)
    if pick['round'] == 1: return 20 + (projected_rank * 0.8)
    else: return 5 + (projected_rank * 0.1)

# ==========================================
# 2. AI LOGIC (Simulated daily actions)
# ==========================================

def update_ai_trade_logic(conn, league_id, user_team_id):
    """Sets AI teams as Buyers or Sellers based on W/L record"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM league_teams WHERE league_id = %s AND team_id != %s", (league_id, user_team_id))
    teams = cur.fetchall()
    
    for t in teams:
        games = t['wins'] + t['losses']
        if games < 10: continue

        win_pct = t['wins'] / games
        
        # SELLER LOGIC (Bad Team < 40%)
        if win_pct < 0.40:
            cur.execute("UPDATE league_players SET trade_status = 'green' WHERE team_id = %s AND age >= 28 AND overall_rating < 85", (t['team_id'],))
            cur.execute("UPDATE league_players SET trade_status = 'red' WHERE team_id = %s AND age <= 24 AND overall_rating > 75", (t['team_id'],))
        # BUYER LOGIC (Good Team > 55%)
        elif win_pct > 0.55:
            cur.execute("UPDATE league_players SET trade_status = 'red' WHERE team_id = %s AND overall_rating >= 80", (t['team_id'],))
            cur.execute("UPDATE league_players SET trade_status = 'green' WHERE team_id = %s AND overall_rating < 75 AND age > 25", (t['team_id'],))
        else:
            cur.execute("UPDATE league_players SET trade_status = 'yellow' WHERE team_id = %s AND trade_status = 'green'", (t['team_id'],))
    conn.commit()

def attempt_ai_signings(conn, league_id):
    """Daily routine for AI teams to fill rosters"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT salary_cap FROM leagues WHERE league_id = %s", (league_id,))
    cap = cur.fetchone()['salary_cap']
    
    cur.execute("""
        SELECT t.team_id, COUNT(p.player_id) as roster_count
        FROM league_teams t
        LEFT JOIN league_players p ON t.team_id = p.team_id
        WHERE t.league_id = %s
        GROUP BY t.team_id HAVING COUNT(p.player_id) < 14
    """, (league_id,))
    needy_teams = cur.fetchall()
    
    cur.execute("SELECT * FROM league_players WHERE team_id IS NULL ORDER BY overall_rating DESC LIMIT 50")
    free_agents = cur.fetchall()
    
    for t in needy_teams:
        if random.random() > 0.3: continue
        space, used = calculate_cap_space(conn, t['team_id'], cap)
        
        for p in free_agents:
            asking = get_player_asking_price(p)
            if asking <= space:
                cur.execute("UPDATE league_players SET team_id = %s, salary_amount = %s WHERE player_id = %s", 
                            (t['team_id'], asking, p['player_id']))
                desc = f"Signed Free Agent {p['first_name']} {p['last_name']} (${asking/1000000:.1f}M)"
                cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'signing')",
                            (league_id, t['team_id'], desc))
                conn.commit()
                free_agents.remove(p) 
                break

def generate_smart_trades(conn, league_id, user_team_id):
    if random.random() > 0.40: return
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM league_players WHERE trade_status = 'green' AND team_id != %s ORDER BY RANDOM() LIMIT 1", (user_team_id,)) 
    player_to_sell = cur.fetchone()
    if not player_to_sell: return
    seller_id = player_to_sell['team_id']
    cur.execute("SELECT team_id FROM league_teams WHERE league_id = %s AND team_id != %s ORDER BY RANDOM() LIMIT 1", (league_id, seller_id))
    buyer_row = cur.fetchone()
    if not buyer_row: return
    buyer_id = buyer_row['team_id']
    
    val = get_player_trade_value(player_to_sell)
    cur.execute("SELECT * FROM league_draft_picks WHERE owner_team_id = %s AND round = 1 LIMIT 1", (buyer_id,))
    pick_to_give = cur.fetchone()
    
    if pick_to_give:
        pick_val = 25
        if pick_val >= (val * 0.85):
            # Only process CPU-CPU trades here for simplicity, or queue offers for user
            if buyer_id != user_team_id and seller_id != user_team_id:
                cur.execute("UPDATE league_players SET team_id = %s WHERE player_id = %s", (buyer_id, player_to_sell['player_id']))
                cur.execute("UPDATE league_draft_picks SET owner_team_id = %s WHERE pick_id = %s", (seller_id, pick_to_give['pick_id']))
                desc = f"Traded {player_to_sell['last_name']} to Team {buyer_id} for Pick"
                cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'trade')", (league_id, seller_id, desc))
                conn.commit()

# ==========================================
# 3. CORE SIMULATION WRAPPERS
# ==========================================

def run_daily_simulation_logic(conn, league_id, user_team_id):
    """Core logic to simulate one day and advance date"""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Get Sim Date and Simulation Mode
    cur.execute("SELECT sim_date, simulation_mode FROM leagues WHERE league_id = %s", (league_id,))
    league_data = cur.fetchone()
    sim_date = league_data['sim_date']
    sim_mode = league_data.get('simulation_mode', 'detailed')

    # 2. Get Games for Today
    cur.execute("""
        SELECT game_id, home_team_id, away_team_id
        FROM league_schedule
        WHERE league_id = %s
          AND day_of_month = EXTRACT(DAY FROM %s::date)
          AND year = EXTRACT(YEAR FROM %s::date)
          AND TRIM(month_name) = TRIM(TO_CHAR(%s::date, 'Month'))
          AND is_played = FALSE
    """, (league_id, sim_date, sim_date, sim_date))
    games = cur.fetchall()
    cur.close()

    # 3. Sim Games (choose simulation mode)
    for g in games:
        if sim_mode == 'fast':
            run_fast_game_simulation(conn, league_id, g['game_id'], g['home_team_id'], g['away_team_id'])
        else:
            run_game_simulation(conn, league_id, g['game_id'], g['home_team_id'], g['away_team_id'])

    # 4. AI Logic (Trades/Signings)
    update_ai_trade_logic(conn, league_id, user_team_id)
    attempt_ai_signings(conn, league_id)
    generate_smart_trades(conn, league_id, user_team_id)

    # 5. Advance Date
    cur = conn.cursor()
    cur.execute("UPDATE leagues SET sim_date = sim_date + INTERVAL '1 day' WHERE league_id = %s", (league_id,))
    conn.commit()
    cur.close()

# ==========================================
# 4. ROUTES: SETUP & DASHBOARD
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/load_league')
def load_league():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT league_id, name, season_year, sim_date, created_at FROM leagues ORDER BY created_at DESC")
    leagues = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('load_league.html', leagues=leagues)

@app.route('/create_league', methods=['GET', 'POST'])
def create_league():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if request.method == 'POST':
        try:
            league_name = request.form['name']
            scenario_id = int(request.form['scenario_id'])
            user_qs_team_id = int(request.form['user_team_id'])
            playoff_teams = int(request.form['playoff_teams'])
            salary_cap = int(request.form['salary_cap'])

            cur.execute("""
                INSERT INTO leagues (name, scenario_source_id, playoff_teams_per_conf, salary_cap, sim_date)
                VALUES (%s, %s, %s, %s, '2024-10-22') RETURNING league_id;
            """, (league_name, scenario_id, playoff_teams, salary_cap))
            new_league_id = cur.fetchone()['league_id']

            id_map = {} 
            cur.execute("SELECT * FROM quick_start_teams WHERE scenario_id = %s", (scenario_id,))
            qs_teams = cur.fetchall()

            user_new_team_id = None
            for t in qs_teams:
                cur.execute("""
                    INSERT INTO league_teams (league_id, city, name, abbrev, conference, division)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING team_id;
                """, (new_league_id, t['city'], t['name'], t['abbrev'], t['conference'], t['division']))
                new_team_id = cur.fetchone()['team_id']
                id_map[t['qs_team_id']] = new_team_id
                if t['qs_team_id'] == user_qs_team_id: user_new_team_id = new_team_id
                
                cur.execute("INSERT INTO league_draft_picks (league_id, owner_team_id, original_team_id, year, round) VALUES (%s, %s, %s, %s, 1)", (new_league_id, new_team_id, new_team_id, 2026))
                cur.execute("INSERT INTO league_draft_picks (league_id, owner_team_id, original_team_id, year, round) VALUES (%s, %s, %s, %s, 2)", (new_league_id, new_team_id, new_team_id, 2026))

            if user_new_team_id:
                cur.execute("UPDATE leagues SET user_team_id = %s WHERE league_id = %s", (user_new_team_id, new_league_id))

            # Bulk insert players (much faster)
            cur.execute("SELECT * FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = %s)", (scenario_id,))
            qs_players = cur.fetchall()

            player_data = []
            for p in qs_players:
                new_team_id = id_map.get(p['qs_team_id'])
                if new_team_id:
                    player_data.append((new_team_id, new_league_id, p['first_name'], p['last_name'], p['position'],
                                      p['age'], p['usage_rating'], p['inside_shooting'], p['outside_shooting'],
                                      p['ft_shooting'], p['passing'], p['speed'], p['guarding'], p['stealing'],
                                      p['blocking'], p['rebounding'], p['overall_rating'], p['contract_years'], p['salary_amount']))

            if player_data:
                args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", x).decode('utf-8') for x in player_data)
                cur.execute("INSERT INTO league_players (team_id, league_id, first_name, last_name, position, age, usage_rating, inside_shooting, outside_shooting, ft_shooting, passing, speed, guarding, stealing, blocking, rebounding, overall_rating, contract_years, salary_amount) VALUES " + args_str)

            # Bulk insert schedule (much faster)
            cur.execute("SELECT * FROM quick_start_schedule WHERE scenario_id = %s", (scenario_id,))
            qs_games = cur.fetchall()

            schedule_data = []
            for g in qs_games:
                new_home = id_map.get(g['home_qs_team_id'])
                new_away = id_map.get(g['away_qs_team_id'])
                if new_home and new_away:
                    schedule_data.append((new_league_id, g['week_number'], g['day_number'], g['day_of_week'],
                                        g['month_name'], g['day_of_month'], g['year'], new_home, new_away))

            if schedule_data:
                args_str = ','.join(cur.mogrify("(%s,%s,%s,%s,%s,%s,%s,%s,%s)", x).decode('utf-8') for x in schedule_data)
                cur.execute("INSERT INTO league_schedule (league_id, week_number, day_number, day_of_week, month_name, day_of_month, year, home_team_id, away_team_id) VALUES " + args_str)

            if user_new_team_id:
                cur.execute("INSERT INTO coaching_strategy (team_id) VALUES (%s)", (user_new_team_id,))

            conn.commit()
            return redirect(url_for('league_dashboard', league_id=new_league_id))
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"CREATE LEAGUE ERROR: {error_details}")  # This will show in Render logs
            conn.rollback()
            cur.close()
            conn.close()
            return f"""
                <html><body style="font-family: Arial; padding: 20px;">
                <h2>Error Creating League</h2>
                <p><strong>Error:</strong> {str(e)}</p>
                <pre style="background: #f5f5f5; padding: 15px; overflow-x: auto;">{error_details}</pre>
                <a href="/create_league">← Back to Create League</a>
                </body></html>
            """, 500
        finally:
            if not cur.closed:
                cur.close()
            if not conn.closed:
                conn.close()

    cur.execute("SELECT scenario_id, name FROM quick_start_scenarios")
    scenarios = cur.fetchall()
    cur.execute("SELECT qs_team_id, city, name FROM quick_start_teams WHERE scenario_id = 1 ORDER BY city")
    teams = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('create_league.html', scenarios=scenarios, teams=teams)

@app.route('/dashboard/<int:league_id>')
def league_dashboard(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    session['user_team_id'] = league['user_team_id']
    sim_date = league['sim_date']
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("SELECT * FROM league_teams WHERE league_id = %s ORDER BY wins DESC, losses ASC", (league_id,))
    teams = cur.fetchall()
    
    # Today's games
    cur.execute("""
        SELECT s.game_id, th.abbrev as home_abv, th.name as home_name, ta.abbrev as away_abv, ta.name as away_name,
               s.home_score, s.away_score, s.is_played
        FROM league_schedule s
        JOIN league_teams th ON s.home_team_id = th.team_id
        JOIN league_teams ta ON s.away_team_id = ta.team_id
        WHERE s.league_id = %s 
          AND s.day_of_month = EXTRACT(DAY FROM %s::date)
          AND s.year = EXTRACT(YEAR FROM %s::date)
          AND TRIM(s.month_name) = TRIM(TO_CHAR(%s::date, 'Month'))
    """, (league_id, sim_date, sim_date, sim_date))
    todays_games = cur.fetchall()
    for g in todays_games:
        g['home_logo'] = get_team_logo(g['home_abv'])
        g['away_logo'] = get_team_logo(g['away_abv'])

    # Recent history for streaks
    cur.execute("SELECT home_team_id, away_team_id, home_score, away_score FROM league_schedule WHERE league_id = %s AND is_played = TRUE ORDER BY game_id DESC", (league_id,))
    played_games = cur.fetchall()
    
    # Explicitly define keys to keep dashboard static
    standings = {'East': defaultdict(list), 'West': defaultdict(list)}
    
    conf_leaders = {'East': None, 'West': None}
    team_history = defaultdict(list)

    for g in played_games:
        res_h = 'W' if g['home_score'] > g['away_score'] else 'L'
        team_history[g['home_team_id']].append(res_h)
        res_a = 'W' if g['away_score'] > g['home_score'] else 'L'
        team_history[g['away_team_id']].append(res_a)

    for team in teams:
        team['is_user'] = (team['team_id'] == league['user_team_id'])
        team['logo_url'] = get_team_logo(team['abbrev'])
        total = team['wins'] + team['losses']
        team['pct'] = "{:.3f}".format(team['wins'] / total) if total > 0 else ".000"
        last_5 = team_history[team['team_id']][:5]
        team['l5'] = f"{last_5.count('W')}-{last_5.count('L')}"
        team['streak_display'] = f"{team['streak_type']}{team['streak_length']}" if team['streak_length'] > 0 else "-"
        conf = team['conference']
        if conf_leaders[conf] is None: conf_leaders[conf] = team
        leader = conf_leaders[conf]
        team['gb'] = calculate_gb(leader['wins'], leader['losses'], team['wins'], team['losses'])
        
        # Add to static standings
        if conf in standings:
            standings[conf][team['division']].append(team)

    cur.close()
    conn.close()
    return render_template('dashboard.html', league=league, standings=standings, todays_games=todays_games, all_leagues=all_leagues)

@app.route('/standings/<int:league_id>')
def league_standings(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("SELECT * FROM league_teams WHERE league_id = %s", (league_id,))
    teams = cur.fetchall()
    for t in teams: t['logo_url'] = get_team_logo(t['abbrev'])
    east = [t for t in teams if t['conference'] == 'East']
    west = [t for t in teams if t['conference'] == 'West']
    east.sort(key=lambda x: (x['wins'] / (x['wins'] + x['losses']) if (x['wins'] + x['losses']) > 0 else 0), reverse=True)
    west.sort(key=lambda x: (x['wins'] / (x['wins'] + x['losses']) if (x['wins'] + x['losses']) > 0 else 0), reverse=True)

    def calc_conf_gb(conf_teams):
        if not conf_teams: return
        leader = conf_teams[0]
        for t in conf_teams:
            t['gb'] = calculate_gb(leader['wins'], leader['losses'], t['wins'], t['losses'])
            t['pct'] = "{:.3f}".format(t['wins'] / (t['wins'] + t['losses'])) if (t['wins'] + t['losses']) > 0 else ".000"

    calc_conf_gb(east)
    calc_conf_gb(west)
    east = calculate_playoff_odds(east)
    west = calculate_playoff_odds(west)
    cur.close()
    conn.close()
    return render_template('standings.html', league=league, east=east, west=west, all_leagues=all_leagues)

# ==========================================
# 5. ROUTES: SIMULATION
# ==========================================

@app.route('/simulate_game/<int:game_id>', methods=['POST'])
def simulate_single_game(game_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT league_id, home_team_id, away_team_id FROM league_schedule WHERE game_id = %s", (game_id,))
    game = cur.fetchone()
    cur.close()
    if game:
        run_game_simulation(conn, game['league_id'], game_id, game['home_team_id'], game['away_team_id'])
        return redirect(url_for('league_schedule', league_id=game['league_id']))
    return "Game not found", 404

@app.route('/simulate_day/<int:league_id>', methods=['POST'])
def simulate_day(league_id):
    try:
        user_team_id = session.get('user_team_id', 61)
        conn = get_db_connection()
        run_daily_simulation_logic(conn, league_id, user_team_id)
        conn.close()

        # Safe redirect handling
        if request.referrer and 'league_schedule' in request.referrer:
            return redirect(url_for('league_schedule', league_id=league_id))
        return redirect(url_for('league_dashboard', league_id=league_id))
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"SIMULATE DAY ERROR: {error_details}")
        return f"""
            <html><body style="font-family: Arial; padding: 20px;">
            <h2>Simulation Error</h2>
            <p><strong>Error:</strong> {str(e)}</p>
            <pre style="background: #f5f5f5; padding: 15px; overflow-x: auto;">{error_details}</pre>
            <a href="/dashboard/{league_id}">← Back to Dashboard</a>
            </body></html>
        """, 500

@app.route('/simulate_week/<int:league_id>', methods=['POST'])
def simulate_week(league_id):
    try:
        user_team_id = session.get('user_team_id', 61)
        conn = get_db_connection()
        for day in range(7):
            print(f"Simulating day {day + 1}/7...")
            run_daily_simulation_logic(conn, league_id, user_team_id)
        conn.close()

        # Safe redirect handling
        if request.referrer and 'league_schedule' in request.referrer:
            return redirect(url_for('league_schedule', league_id=league_id))
        return redirect(url_for('league_dashboard', league_id=league_id))
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"SIMULATE WEEK ERROR: {error_details}")
        return f"""
            <html><body style="font-family: Arial; padding: 20px;">
            <h2>Simulation Error</h2>
            <p><strong>Error:</strong> {str(e)}</p>
            <pre style="background: #f5f5f5; padding: 15px; overflow-x: auto;">{error_details}</pre>
            <a href="/dashboard/{league_id}">← Back to Dashboard</a>
            </body></html>
        """, 500

# ==========================================
# 6. ROUTES: STATS & TEAM VIEWS
# ==========================================

@app.route('/team/<int:team_id>')
def team_home(team_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (team_id,))
    team = cur.fetchone()
    if not team: return "Team not found", 404
    team['logo_url'] = get_team_logo(team['abbrev'])
    league_id = team['league_id']
    
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()

    # Calculate League Average Efficiency
    cur.execute("""
        SELECT AVG(eff_per_game) as avg_eff
        FROM (
            SELECT 
                (
                    (COALESCE(SUM(b.points),0) + COALESCE(SUM(b.rebounds),0) + COALESCE(SUM(b.assists),0) + 
                     COALESCE(SUM(b.steals),0) + COALESCE(SUM(b.blocks),0)) - 
                    ((COALESCE(SUM(b.fg_attempts),0) - COALESCE(SUM(b.fg_made),0)) + 
                     (COALESCE(SUM(b.ft_attempts),0) - COALESCE(SUM(b.ft_made),0)) + 
                     COALESCE(SUM(b.turnovers),0))
                ) / NULLIF(COUNT(b.game_id), 0) as eff_per_game
            FROM league_players p 
            JOIN league_box_scores b ON p.player_id = b.player_id 
            WHERE p.league_id = %s 
            GROUP BY p.player_id
        ) as player_stats
    """, (league_id,))
    
    row = cur.fetchone()
    league_avg_eff = float(row['avg_eff']) if row and row['avg_eff'] is not None else 10.0

    cur.execute("""
        SELECT team_id, RANK() OVER (ORDER BY wins DESC, losses ASC) as rank 
        FROM league_teams 
        WHERE league_id = %s AND conference = %s
    """, (league_id, team['conference']))
    rankings = cur.fetchall()
    team_rank = next((item['rank'] for item in rankings if item['team_id'] == team_id), "-")

    cur.execute("""
        SELECT p.*, 
               COUNT(b.game_id) as gp,
               COALESCE(AVG(b.points), 0) as ppg,
               COALESCE(AVG(b.rebounds), 0) as rpg,
               COALESCE(AVG(b.assists), 0) as apg,
               COALESCE(AVG(b.plus_minus), 0) as pm,
               COALESCE(SUM(
                    (b.points + b.rebounds + b.assists + b.steals + b.blocks) - 
                    ((b.fg_attempts - b.fg_made) + (b.ft_attempts - b.ft_made) + b.turnovers)
               ), 0) as total_eff
        FROM league_players p 
        LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.team_id = %s 
        GROUP BY p.player_id
    """, (team_id,))
    roster = cur.fetchall()

    for p in roster:
        if p['gp'] > 0:
            eff = p['total_eff'] / p['gp']
            p['vaa'] = "{:+.0f}".format(eff - league_avg_eff)
            p['vaa_val'] = eff - league_avg_eff
        else:
            p['vaa'] = "+0"
            p['vaa_val'] = -99
        p['ppg'] = "{:.1f}".format(p['ppg'])
        p['rpg'] = "{:.1f}".format(p['rpg'])
        p['apg'] = "{:.1f}".format(p['apg'])
        p['pm'] = "{:+.1f}".format(p['pm'])
        raw_salary = float(p['salary_amount']) if p['salary_amount'] else 0.0
        p['salary_fmt'] = "${:.1f}M".format(raw_salary / 1000000.0)

    roster.sort(key=lambda x: x['vaa_val'], reverse=True)
    cur.close()
    conn.close()
    return render_template('team.html', team=team, league=league, all_leagues=all_leagues, roster=roster, rank=team_rank)

@app.route('/league_stats/<int:league_id>')
def league_stats(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    
    cur.execute("""
        SELECT p.player_id, p.first_name, p.last_name, p.position, p.overall_rating, p.age,
            t.abbrev as team_abbrev, t.team_id,
            COUNT(b.game_id) as gp,
            COALESCE(SUM(b.minutes), 0) as total_min, COALESCE(SUM(b.points), 0) as total_pts,
            COALESCE(SUM(b.rebounds), 0) as total_reb, COALESCE(SUM(b.assists), 0) as total_ast,
            COALESCE(SUM(b.steals), 0) as total_stl, COALESCE(SUM(b.blocks), 0) as total_blk,
            COALESCE(SUM(b.turnovers), 0) as total_tov, COALESCE(SUM(b.fg_made), 0) as total_fgm,
            COALESCE(SUM(b.fg_attempts), 0) as total_fga
        FROM league_players p
        JOIN league_teams t ON p.team_id = t.team_id
        LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.league_id = %s GROUP BY p.player_id, t.team_id
    """, (league_id,))
    raw_stats = cur.fetchall()
    
    stats = []
    active_effs = []
    for p in raw_stats:
        gp = p['gp']
        if gp > 0:
            eff = (p['total_pts'] + p['total_reb'] + p['total_ast'] + p['total_stl'] + p['total_blk']) - ((p['total_fga']-p['total_fgm']) + p['total_tov'])
            p['eff_per_game'] = eff / gp
            active_effs.append(p['eff_per_game'])
            p['mpg'] = p['total_min'] / gp; p['ppg'] = p['total_pts'] / gp
            p['rpg'] = p['total_reb'] / gp; p['apg'] = p['total_ast'] / gp
            p['spg'] = p['total_stl'] / gp; p['bpg'] = p['total_blk'] / gp
        else:
            p['eff_per_game'] = 0
            p['mpg']=0; p['ppg']=0; p['rpg']=0; p['apg']=0; p['spg']=0; p['bpg']=0
        
        p['mpg_fmt']="{:.1f}".format(p['mpg']); p['ppg_fmt']="{:.1f}".format(p['ppg'])
        p['rpg_fmt']="{:.1f}".format(p['rpg']); p['apg_fmt']="{:.1f}".format(p['apg'])
        p['spg_fmt']="{:.1f}".format(p['spg']); p['bpg_fmt']="{:.1f}".format(p['bpg'])
        stats.append(p)
        
    league_avg = sum(active_effs)/len(active_effs) if active_effs else 10.0
    for p in stats:
        if p['gp'] > 0: p['vaa'] = p['eff_per_game'] - league_avg
        else: p['vaa'] = -league_avg
        p['vaa_fmt'] = "{:+.0f}".format(p['vaa'])
        
    stats.sort(key=lambda x: x['vaa'], reverse=True)
    cur.close()
    conn.close()
    return render_template('league_stats.html', league=league, all_leagues=all_leagues, stats=stats)

@app.route('/my_team_stats')
def my_team_stats():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT l.* FROM leagues l JOIN league_teams t ON t.league_id = l.league_id WHERE t.team_id = %s", (user_team_id,))
    league = cur.fetchone()
    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (user_team_id,))
    team = cur.fetchone()
    team['logo_url'] = get_team_logo(team['abbrev'])
    cur.execute("""
        SELECT p.player_id, p.first_name, p.last_name, p.position, p.age, p.overall_rating,
            COUNT(b.game_id) as gp, COALESCE(SUM(b.minutes), 0) as total_min, COALESCE(SUM(b.points), 0) as total_pts,
            COALESCE(SUM(b.rebounds), 0) as total_reb, COALESCE(SUM(b.assists), 0) as total_ast,
            COALESCE(SUM(b.steals), 0) as total_stl, COALESCE(SUM(b.blocks), 0) as total_blk,
            COALESCE(SUM(b.turnovers), 0) as total_tov, COALESCE(SUM(b.fg_made), 0) as total_fgm,
            COALESCE(SUM(b.fg_attempts), 0) as total_fga, COALESCE(SUM(b.threes_made), 0) as total_3pm,
            COALESCE(SUM(b.threes_attempts), 0) as total_3pa, COALESCE(SUM(b.ft_made), 0) as total_ftm,
            COALESCE(SUM(b.ft_attempts), 0) as total_fta
        FROM league_players p LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.team_id = %s GROUP BY p.player_id
    """, (user_team_id,))
    raw_stats = cur.fetchall()
    stats = []
    for p in raw_stats:
        gp = p['gp']
        if gp > 0:
            p['mpg'] = "{:.1f}".format(p['total_min'] / gp); p['ppg'] = "{:.1f}".format(p['total_pts'] / gp)
            p['rpg'] = "{:.1f}".format(p['total_reb'] / gp); p['apg'] = "{:.1f}".format(p['total_ast'] / gp)
            p['spg'] = "{:.1f}".format(p['total_stl'] / gp); p['bpg'] = "{:.1f}".format(p['total_blk'] / gp)
            p['tov'] = "{:.1f}".format(p['total_tov'] / gp)
            p['fg_pct'] = (p['total_fgm'] / p['total_fga'] * 100) if p['total_fga'] > 0 else 0.0
            p['fg_pct_fmt'] = "{:.1f}%".format(p['fg_pct'])
            p['three_pct'] = (p['total_3pm'] / p['total_3pa'] * 100) if p['total_3pa'] > 0 else 0.0
            p['three_pct_fmt'] = "{:.1f}%".format(p['three_pct'])
            p['ft_pct'] = (p['total_ftm'] / p['total_fta'] * 100) if p['total_fta'] > 0 else 0.0
            p['ft_pct_fmt'] = "{:.1f}%".format(p['ft_pct'])
        else:
            p['mpg']="0.0"; p['ppg']="0.0"; p['rpg']="0.0"; p['apg']="0.0"; p['spg']="0.0"; p['bpg']="0.0"; p['tov']="0.0"
            p['fg_pct']=0; p['fg_pct_fmt']="-"; p['three_pct']=0; p['three_pct_fmt']="-"; p['ft_pct']=0; p['ft_pct_fmt']="-"
        stats.append(p)
    stats.sort(key=lambda x: float(x['ppg']), reverse=True)
    cur.close()
    conn.close()
    return render_template('team_stats.html', league=league, team=team, stats=stats)

@app.route('/boxscore/<int:game_id>')
def boxscore(game_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT s.*, th.name as home_name, th.city as home_city, th.abbrev as home_abv,
               ta.name as away_name, ta.city as away_city, ta.abbrev as away_abv
        FROM league_schedule s
        JOIN league_teams th ON s.home_team_id = th.team_id
        JOIN league_teams ta ON s.away_team_id = ta.team_id
        WHERE s.game_id = %s
    """, (game_id,))
    game = cur.fetchone()
    if not game: return "Game not found", 404
    game['home_logo'] = get_team_logo(game['home_abv'])
    game['away_logo'] = get_team_logo(game['away_abv'])
    league_id = game['league_id']
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("""
        SELECT p.first_name, p.last_name, p.position, p.age, b.*
        FROM league_box_scores b
        JOIN league_players p ON b.player_id = p.player_id
        WHERE b.game_id = %s ORDER BY b.points DESC
    """, (game_id,))
    stats = cur.fetchall()
    home_stats = [s for s in stats if s['team_id'] == game['home_team_id']]
    away_stats = [s for s in stats if s['team_id'] == game['away_team_id']]
    cur.execute("SELECT * FROM league_game_events WHERE game_id = %s ORDER BY event_id ASC", (game_id,))
    pbp = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('boxscore.html', game=game, league=league, all_leagues=all_leagues, home_stats=home_stats, away_stats=away_stats, pbp=pbp)

# ==========================================
# 7. ROUTES: STRATEGY & MANAGEMENT
# ==========================================

@app.route('/strategy')
def coach_strategy():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT l.* FROM leagues l JOIN league_teams t ON t.league_id=l.league_id WHERE t.team_id=%s", (user_team_id,))
    league = cur.fetchone()
    cur.execute("SELECT * FROM coaching_strategy WHERE team_id=%s", (user_team_id,))
    strategy = cur.fetchone()
    if strategy is None:
        cur.execute("INSERT INTO coaching_strategy (team_id) VALUES (%s)", (user_team_id,))
        conn.commit()
        cur.execute("SELECT * FROM coaching_strategy WHERE team_id=%s", (user_team_id,))
        strategy = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('coach_strategy.html', strategy=strategy, league=league)

@app.route('/save_strategy', methods=['POST'])
def save_strategy():
    data = request.json
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE coaching_strategy SET offense_focus=%s, defense_focus=%s, bench_minutes=%s, rest_strategy=%s, training_focus=%s WHERE team_id=%s",
                (data.get('offense_focus'), data.get('defense_focus'), data.get('bench_minutes'), data.get('rest_strategy'), data.get('training_focus'), user_team_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/toggle_simulation_mode/<int:league_id>', methods=['POST'])
def toggle_simulation_mode(league_id):
    """Toggle between detailed and fast simulation modes"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get current mode
    cur.execute("SELECT simulation_mode FROM leagues WHERE league_id = %s", (league_id,))
    current_mode = cur.fetchone().get('simulation_mode', 'detailed')

    # Toggle mode
    new_mode = 'fast' if current_mode == 'detailed' else 'detailed'

    cur.execute("UPDATE leagues SET simulation_mode = %s WHERE league_id = %s", (new_mode, league_id))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'new_mode': new_mode,
        'message': f"Switched to {new_mode} simulation mode"
    })

@app.route('/reassign_contracts/<int:league_id>', methods=['POST'])
def reassign_contracts_route(league_id):
    """Reassign all player contracts to fit under salary cap"""
    conn = get_db_connection()

    result = reassign_league_contracts(conn, league_id)

    conn.close()

    if result['success']:
        return jsonify({
            'success': True,
            'message': f"Reassigned {result['players_updated']} contracts across {result['teams_updated']} teams. Cap: ${result['salary_cap']:,}"
        })
    else:
        return jsonify({
            'success': False,
            'message': result.get('error', 'Unknown error')
        })

@app.route('/depth_chart', methods=['GET', 'POST'])
def depth_chart():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if request.method == 'POST':
        data = request.json
        for idx, pid in enumerate(data.get('player_ids', [])):
            cur.execute("UPDATE league_players SET rotation_order=%s WHERE player_id=%s AND team_id=%s", (idx+1, pid, user_team_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    cur.execute("SELECT l.* FROM leagues l JOIN league_teams t ON t.league_id=l.league_id WHERE t.team_id=%s", (user_team_id,))
    league = cur.fetchone()
    cur.execute("SELECT * FROM league_teams WHERE team_id=%s", (user_team_id,))
    team = cur.fetchone()
    team['logo_url'] = get_team_logo(team['abbrev'])
    cur.execute("SELECT player_id, first_name, last_name, position, overall_rating, age, rotation_order, trade_status, salary_amount, contract_years FROM league_players WHERE team_id=%s ORDER BY rotation_order ASC, overall_rating DESC", (user_team_id,))
    roster = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('depth_chart.html', league=league, team=team, roster=roster)

# ==========================================
# 8. ROUTES: TRADES & TRANSACTIONS
# ==========================================

@app.route('/trade_block', methods=['GET'])
def trade_block():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT l.* FROM leagues l JOIN league_teams t ON t.league_id=l.league_id WHERE t.team_id=%s", (user_team_id,))
    league = cur.fetchone()
    cur.execute("SELECT * FROM league_teams WHERE team_id=%s", (user_team_id,))
    user_team = cur.fetchone()
    user_team['logo_url'] = get_team_logo(user_team['abbrev'])
    cur.execute("SELECT * FROM league_players WHERE team_id=%s ORDER BY overall_rating DESC", (user_team_id,))
    user_players = cur.fetchall()
    cur.execute("SELECT p.*, t.abbrev as original_owner FROM league_draft_picks p JOIN league_teams t ON p.original_team_id=t.team_id WHERE p.owner_team_id=%s", (user_team_id,))
    user_picks = cur.fetchall()
    cur.execute("SELECT * FROM league_teams WHERE league_id=%s AND team_id!=%s ORDER BY city", (league['league_id'], user_team_id))
    other_teams = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('trade_block.html', league=league, user_team=user_team, user_players=user_players, user_picks=user_picks, other_teams=other_teams)

@app.route('/get_team_assets/<int:team_id>')
def get_team_assets(team_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT player_id, first_name, last_name, position, overall_rating, age, salary_amount, trade_status FROM league_players WHERE team_id=%s ORDER BY overall_rating DESC", (team_id,))
    players = cur.fetchall()
    cur.execute("SELECT p.*, t.abbrev as original_owner FROM league_draft_picks p JOIN league_teams t ON p.original_team_id=t.team_id WHERE p.owner_team_id=%s", (team_id,))
    picks = cur.fetchall()
    cur.close()
    conn.close()
    for p in players:
        p['salary_amount'] = float(p['salary_amount'])
        p['formatted_salary'] = "${:.1f}M".format(p['salary_amount']/1000000)
    return jsonify({'players': players, 'picks': picks})

@app.route('/update_trade_status', methods=['POST'])
def update_trade_status():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE league_players SET trade_status = %s WHERE player_id = %s", (data['status'], data['player_id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/propose_trade', methods=['POST'])
def propose_trade():
    data = request.json
    user_assets = data.get('user_assets', [])
    partner_assets = data.get('partner_assets', [])
    partner_team_id = data.get('partner_team_id')
    
    if len(user_assets) > 3 or len(partner_assets) > 3:
        return jsonify({'success': False, 'message': 'Max 3 assets per side.'})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    user_team_id = session.get('user_team_id', 61)
    cur.execute("SELECT league_id FROM league_teams WHERE team_id = %s", (user_team_id,))
    league_id = cur.fetchone()['league_id']

    user_total_value = 0; partner_total_value = 0
    user_salary_out = 0; partner_salary_out = 0
    assets_received_names = []
    
    for asset in user_assets:
        if asset['type'] == 'player':
            cur.execute("SELECT * FROM league_players WHERE player_id=%s", (asset['id'],))
            p = cur.fetchone()
            user_total_value += get_player_trade_value(p)
            user_salary_out += float(p['salary_amount'])
        elif asset['type'] == 'pick':
            cur.execute("SELECT * FROM league_teams WHERE team_id=%s", (asset['original_team_id'],))
            t_rec = cur.fetchone()
            if not t_rec: t_rec = {'wins': 0, 'losses': 0}
            cur.execute("SELECT * FROM league_draft_picks WHERE pick_id=%s", (asset['id'],))
            pick = cur.fetchone()
            user_total_value += get_pick_trade_value(pick, t_rec)

    max_partner_ovr = 0
    for asset in partner_assets:
        if asset['type'] == 'player':
            cur.execute("SELECT * FROM league_players WHERE player_id=%s", (asset['id'],))
            p = cur.fetchone()
            partner_total_value += get_player_trade_value(p)
            partner_salary_out += float(p['salary_amount'])
            if p['overall_rating'] > max_partner_ovr: max_partner_ovr = p['overall_rating']
            assets_received_names.append(f"{p['first_name'][0]}. {p['last_name']}")
        elif asset['type'] == 'pick':
            cur.execute("SELECT * FROM league_teams WHERE team_id=%s", (asset['original_team_id'],))
            t_rec = cur.fetchone()
            cur.execute("SELECT * FROM league_draft_picks WHERE pick_id=%s", (asset['id'],))
            pick = cur.fetchone()
            partner_total_value += get_pick_trade_value(pick, t_rec)
            assets_received_names.append(f"{pick['year']} R{pick['round']} Pick")

    salary_diff_ratio = 1.0
    if user_salary_out > 10000000 or partner_salary_out > 10000000:
        if partner_salary_out > 0: salary_diff_ratio = user_salary_out / partner_salary_out
    
    salary_match = 0.8 <= salary_diff_ratio <= 1.25
    decision = "rejected"
    message = "Not interested."
    threshold = 1.0
    
    if max_partner_ovr >= 90: threshold = 1.4; message="Hesitant to move a superstar."
    elif max_partner_ovr >= 85: threshold = 1.2; message="Valuing their star highly."

    if not salary_match:
        message = "Salaries do not match (must be +/- 20%)."
    elif user_total_value >= (partner_total_value * threshold):
        decision = "accepted"
        message = "Trade Accepted!"
        for asset in user_assets:
            if asset['type'] == 'player': cur.execute("UPDATE league_players SET team_id=%s WHERE player_id=%s", (partner_team_id, asset['id']))
            elif asset['type'] == 'pick': cur.execute("UPDATE league_draft_picks SET owner_team_id=%s WHERE pick_id=%s", (partner_team_id, asset['id']))
        for asset in partner_assets:
            if asset['type'] == 'player': cur.execute("UPDATE league_players SET team_id=%s WHERE player_id=%s", (user_team_id, asset['id']))
            elif asset['type'] == 'pick': cur.execute("UPDATE league_draft_picks SET owner_team_id=%s WHERE pick_id=%s", (user_team_id, asset['id']))
        
        asset_str = ", ".join(assets_received_names) if assets_received_names else "Salary dump"
        desc = f"Traded for: {asset_str}"
        cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'trade')", (league_id, user_team_id, desc))
        conn.commit()
    else:
        gap = int((partner_total_value * threshold) - user_total_value)
        message = f"Offer too low. Gap: {gap} pts."

    cur.close()
    conn.close()
    return jsonify({'decision': decision, 'message': message})

@app.route('/transactions')
def transactions():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT league_id FROM league_teams WHERE team_id=%s", (user_team_id,))
    league_id = cur.fetchone()['league_id']
    cur.execute("SELECT * FROM leagues WHERE league_id=%s", (league_id,))
    league = cur.fetchone()
    cur.execute("""
        SELECT tr.*, t.city, t.name, t.abbrev 
        FROM league_transactions tr
        JOIN league_teams t ON tr.team_id = t.team_id
        WHERE tr.league_id = %s
        ORDER BY tr.created_at DESC LIMIT 100
    """, (league_id,))
    transactions = cur.fetchall()
    for t in transactions:
        t['logo_url'] = get_team_logo(t['abbrev'])
        t['date_fmt'] = t['created_at'].strftime('%b %d')
    cur.close()
    conn.close()
    return render_template('transactions.html', league=league, transactions=transactions)

# ==========================================
# 9. ROUTES: FREE AGENCY & FINANCES
# ==========================================

@app.route('/free_agency')
def free_agency():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues l JOIN league_teams t ON l.league_id=t.league_id WHERE t.team_id=%s", (user_team_id,))
    league = cur.fetchone()
    cap_space, used_cap = calculate_cap_space(conn, user_team_id, league['salary_cap'])
    cur.execute("SELECT * FROM league_players WHERE team_id IS NULL ORDER BY overall_rating DESC")
    free_agents = cur.fetchall()
    for p in free_agents: p['asking_price'] = get_player_asking_price(p)
    cur.close()
    conn.close()
    return render_template('free_agency.html', league=league, free_agents=free_agents, cap_space=cap_space, used_cap=used_cap, salary_cap=league['salary_cap'])

@app.route('/negotiate', methods=['POST'])
def negotiate():
    data = request.json
    player_id = data.get('player_id')
    offer_amount = float(data.get('offer_amount'))
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT salary_cap, league_id FROM leagues WHERE league_id = (SELECT league_id FROM league_teams WHERE team_id=%s)", (user_team_id,))
    row = cur.fetchone()
    salary_cap = row['salary_cap']
    league_id = row['league_id']
    space, used = calculate_cap_space(conn, user_team_id, salary_cap)
    
    if offer_amount > space: return jsonify({'decision': 'error', 'message': 'Not enough cap space!'})
    cur.execute("SELECT * FROM league_players WHERE player_id = %s", (player_id,))
    player = cur.fetchone()
    asking_price = get_player_asking_price(player)
    ratio = offer_amount / asking_price
    decision = "reject"
    message = "The agent hangs up."
    
    if ratio >= 1.0:
        decision = "accepted"
        message = "Deal! Player signed."
        cur.execute("UPDATE league_players SET team_id = %s, salary_amount = %s WHERE player_id = %s", (user_team_id, offer_amount, player_id))
        desc = f"Signed {player['first_name']} {player['last_name']} for ${offer_amount/1000000:.2f}M"
        cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'signing')", (league_id, user_team_id, desc))
        conn.commit()
    elif ratio >= 0.85:
        decision = "counter"
        counter = int(asking_price * 0.95)
        message = f"Close. We would accept ${counter/1000000:.2f}M."
    else:
        decision = "insulted"
        message = "That offer is insulting."
    cur.close()
    conn.close()
    return jsonify({'decision': decision, 'message': message, 'likelihood': int(min(ratio * 100, 100))})

@app.route('/finances')
def finances():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT l.* FROM leagues l 
        JOIN league_teams t ON l.league_id = t.league_id 
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (user_team_id,))
    team = cur.fetchone()
    
    league_cap = float(league['salary_cap'])
    cur.execute("""
        SELECT player_id, first_name, last_name, position, age, overall_rating, 
               salary_amount, contract_years, trade_status
        FROM league_players 
        WHERE team_id = %s 
        ORDER BY salary_amount DESC
    """, (user_team_id,))
    roster = cur.fetchall()
    
    outlook = {
        'current': {'year': '2025', 'cap': league_cap, 'committed': 0},
        'year_2':  {'year': '2026', 'cap': league_cap * 1.05, 'committed': 0},
        'year_3':  {'year': '2027', 'cap': league_cap * 1.10, 'committed': 0},
        'year_4':  {'year': '2028', 'cap': league_cap * 1.15, 'committed': 0}
    }
    
    for p in roster:
        salary = float(p['salary_amount'])
        years = p['contract_years']
        p['salary_fmt'] = "${:,.2f}M".format(salary / 1000000)
        p['asking_price'] = get_player_asking_price(p)
        
        if p['age'] <= 26: p['target_years'] = 5
        elif p['age'] <= 31: p['target_years'] = 4
        elif p['age'] <= 34: p['target_years'] = 2
        else: p['target_years'] = 1
        p['target_contract_fmt'] = "${:.1f}M / {} Yrs".format(p['asking_price']/1000000, p['target_years'])

        outlook['current']['committed'] += salary
        if years >= 2: outlook['year_2']['committed'] += salary
        if years >= 3: outlook['year_3']['committed'] += salary
        if years >= 4: outlook['year_4']['committed'] += salary

    for k, v in outlook.items():
        v['space'] = v['cap'] - v['committed']
        v['pct'] = min(100, (v['committed'] / v['cap']) * 100)
        v['committed_fmt'] = "${:,.1f}M".format(v['committed'] / 1000000)
        v['cap_fmt'] = "${:,.1f}M".format(v['cap'] / 1000000)
        v['space_fmt'] = "${:,.1f}M".format(v['space'] / 1000000)
        if v['pct'] > 100: v['color'] = '#ef4444' 
        elif v['pct'] > 90: v['color'] = '#f59e0b'
        else: v['color'] = '#10b981'

    cur.close()
    conn.close()
    return render_template('finances.html', league=league, all_leagues=all_leagues, team=team, roster=roster, outlook=outlook)

@app.route('/extend_player', methods=['POST'])
def extend_player():
    data = request.json
    player_id = data.get('player_id')
    offer_salary = float(data.get('salary'))
    offer_years = int(data.get('years'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM league_players WHERE player_id = %s", (player_id,))
    player = cur.fetchone()
    asking_salary = get_player_asking_price(player)
    
    if player['age'] <= 26: target_years = 5
    elif player['age'] <= 31: target_years = 4
    elif player['age'] <= 34: target_years = 2
    else: target_years = 1

    salary_ratio = offer_salary / asking_salary
    decision = "rejected"
    message = "Agent: No deal."
    
    if salary_ratio < 0.70:
        message = "Agent: 'That number is insulting. We are done here.'"
    elif salary_ratio < 0.85:
        message = f"Agent: 'We are far apart on money. We want closer to ${asking_salary/1000000:.1f}M.'"
    elif salary_ratio < 0.95:
        message = "Agent: 'You're close on the money, but not quite there.'"
    else:
        if offer_years < (target_years - 1):
             message = f"Agent: 'The money is good, but we need more security. We want {target_years} years.'"
        else:
            decision = "accepted"
            message = "Agent: 'We accept! Great doing business.'"
            new_total_years = player['contract_years'] + offer_years
            cur.execute("UPDATE league_players SET contract_years = %s, salary_amount = %s WHERE player_id = %s", (new_total_years, offer_salary, player_id))
            desc = f"Signed {player['last_name']} to {offer_years}yr extension (${offer_salary/1000000:.1f}M/yr)"
            cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'extension')", (player['league_id'], player['team_id'], desc))
            conn.commit()

    cur.close()
    conn.close()
    return jsonify({'success': (decision == 'accepted'), 'message': message})

# ==========================================
# 10. ROUTES: SCHEDULING
# ==========================================

@app.route('/league_schedule/<int:league_id>')
def league_schedule(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("""
        SELECT s.*, th.abbrev as home_abv, th.name as home_name, ta.abbrev as away_abv, ta.name as away_name
        FROM league_schedule s
        JOIN league_teams th ON s.home_team_id = th.team_id
        JOIN league_teams ta ON s.away_team_id = ta.team_id
        WHERE s.league_id = %s ORDER BY s.year ASC, s.day_number ASC
    """, (league_id,))
    all_games = cur.fetchall()
    sim_date = league['sim_date']
    month_map = {name: i for i, name in enumerate(calendar.month_name) if name}
    schedule_by_month = defaultdict(list)
    for g in all_games:
        g['home_logo'] = get_team_logo(g['home_abv'])
        g['away_logo'] = get_team_logo(g['away_abv'])
        is_today = (g['day_of_month'] == sim_date.day and g['month_name'].strip() == sim_date.strftime('%B') and g['year'] == sim_date.year)
        g['is_today'] = is_today
        try:
            g_month_num = month_map.get(g['month_name'].strip(), 1)
            game_date = datetime.date(g['year'], g_month_num, g['day_of_month'])
            if game_date < sim_date and not g['is_played']: g['status_label'] = 'Postponed'
            else: g['status_label'] = 'Upcoming'
        except: g['status_label'] = 'Upcoming'
        schedule_by_month[f"{g['month_name']} {g['year']}"].append(g)
    cur.close()
    conn.close()
    return render_template('schedule.html', league=league, schedule_by_month=schedule_by_month, all_leagues=all_leagues)

@app.route('/team_schedule/<int:team_id>')
def team_schedule(team_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT t.*, l.league_id, l.name as league_name, l.sim_date 
        FROM league_teams t 
        JOIN leagues l ON t.league_id = l.league_id 
        WHERE t.team_id = %s
    """, (team_id,))
    team = cur.fetchone()
    if not team: return "Team not found", 404
    league_id = team['league_id']
    team['logo_url'] = get_team_logo(team['abbrev'])
    cur.execute("SELECT team_id, city, name FROM league_teams WHERE league_id = %s ORDER BY city", (league_id,))
    all_teams_list = cur.fetchall()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("""
        SELECT s.*, th.abbrev as home_abv, th.name as home_name, ta.abbrev as away_abv, ta.name as away_name
        FROM league_schedule s
        JOIN league_teams th ON s.home_team_id = th.team_id
        JOIN league_teams ta ON s.away_team_id = ta.team_id
        WHERE s.league_id = %s AND (s.home_team_id = %s OR s.away_team_id = %s)
        ORDER BY s.year ASC, s.day_number ASC
    """, (league_id, team_id, team_id))
    raw_games = cur.fetchall()
    games = []
    wins = 0; losses = 0
    for g in raw_games:
        if g['home_team_id'] == team_id:
            g['is_home'] = True; g['opp_name'] = g['away_name']; g['opp_abv'] = g['away_abv']
            g['opp_logo'] = get_team_logo(g['away_abv'])
        else:
            g['is_home'] = False; g['opp_name'] = g['home_name']; g['opp_abv'] = g['home_abv']
            g['opp_logo'] = get_team_logo(g['home_abv'])
        if g['is_played']:
            home_score = g['home_score']; away_score = g['away_score']
            if g['is_home']:
                is_win = home_score > away_score
                g['result_display'] = f"W {home_score}-{away_score}" if is_win else f"L {home_score}-{away_score}"
            else:
                is_win = away_score > home_score
                g['result_display'] = f"W {away_score}-{home_score}" if is_win else f"L {away_score}-{home_score}"
            if is_win: wins += 1; g['result_class'] = 'win-badge'
            else: losses += 1; g['result_class'] = 'loss-badge'
        else:
            g['result_display'] = "-"; g['result_class'] = ''
        games.append(g)
    team['record'] = f"{wins}-{losses}"
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('team_schedule.html', league=league, team=team, games=games, all_teams_list=all_teams_list, all_leagues=all_leagues)

# ==========================================
# 11. ROUTES: PLAYOFFS & HISTORY
# ==========================================

@app.route('/init_playoffs/<int:league_id>')
def init_playoffs(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) as count FROM league_playoff_series WHERE league_id = %s", (league_id,))
    if cur.fetchone()['count'] > 0:
        return redirect(url_for('playoffs_view', league_id=league_id))
    
    teams = {'East': [], 'West': []}
    cur.execute("SELECT * FROM league_teams WHERE league_id = %s", (league_id,))
    all_teams = cur.fetchall()
    for t in all_teams: teams[t['conference']].append(t)
    for conf in teams: teams[conf].sort(key=lambda x: x['wins'], reverse=True)
    
    matchups_order = [(0, 7), (3, 4), (2, 5), (1, 6)] 
    for conf_name, conf_teams in teams.items():
        if len(conf_teams) < 8: return "Error: Need 8 teams per conference"
        for idx, (high_seed_idx, low_seed_idx) in enumerate(matchups_order):
            high = conf_teams[high_seed_idx]; low = conf_teams[low_seed_idx]
            label = f"{conf_name} R1: ({high_seed_idx+1}) {high['abbrev']} vs ({low_seed_idx+1}) {low['abbrev']}"
            cur.execute("""
                INSERT INTO league_playoff_series (league_id, round_num, conference, team1_id, team2_id, series_label)
                VALUES (%s, 1, %s, %s, %s, %s) RETURNING series_id
            """, (league_id, conf_name, high['team_id'], low['team_id'], label))
            series_id = cur.fetchone()['series_id']
            schedule_playoff_game(conn, league_id, series_id, high['team_id'], low['team_id'])
    conn.commit()
    return redirect(url_for('playoffs_view', league_id=league_id))

def schedule_playoff_game(conn, league_id, series_id, home_id, away_id):
    cur = conn.cursor()
    cur.execute("SELECT sim_date FROM leagues WHERE league_id=%s", (league_id,))
    sim_date = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO league_schedule (league_id, home_team_id, away_team_id, playoff_series_id, is_played, year, month_name, day_of_month)
        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s)
    """, (league_id, home_id, away_id, series_id, sim_date.year, sim_date.strftime('%B'), sim_date.day))
    conn.commit()

@app.route('/playoffs/<int:league_id>')
def playoffs_view(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()

    cur.execute("""
        SELECT s.*, 
               t1.abbrev as t1_abv, t1.name as t1_name, t1.city as t1_city,
               t2.abbrev as t2_abv, t2.name as t2_name, t2.city as t2_city
        FROM league_playoff_series s
        JOIN league_teams t1 ON s.team1_id = t1.team_id
        JOIN league_teams t2 ON s.team2_id = t2.team_id
        WHERE s.league_id = %s ORDER BY series_id
    """, (league_id,))
    series_raw = cur.fetchall()
    
    bracket = {'West': {1: [], 2: [], 3: []}, 'East': {1: [], 2: [], 3: []}, 'Finals': []}
    active_series = [] 
    champion = None

    for s in series_raw:
        s['t1_logo'] = get_team_logo(s['t1_abv']); s['t2_logo'] = get_team_logo(s['t2_abv'])
        if s['team1_wins'] < 4 and s['team2_wins'] < 4: active_series.append(s)
        
        if s['conference'] == 'Finals': 
            bracket['Finals'].append(s)
            if s['winner_team_id']:
                cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (s['winner_team_id'],))
                champion = cur.fetchone()
                champion['logo_url'] = get_team_logo(champion['abbrev'])
        else: 
            bracket[s['conference']][s['round_num']].append(s)

    games_map = {}
    if active_series:
        ids = tuple([s['series_id'] for s in active_series])
        if ids:
            cur.execute("SELECT * FROM league_schedule WHERE playoff_series_id IN %s AND is_played = FALSE ORDER BY game_id ASC", (ids,))
            games = cur.fetchall()
            for g in games:
                if g['playoff_series_id'] not in games_map: games_map[g['playoff_series_id']] = g
    
    cur.close()
    conn.close()
    return render_template('playoffs.html', league=league, all_leagues=all_leagues, bracket=bracket, active_series=active_series, next_games=games_map, champion=champion)

@app.route('/sim_playoff_series/<int:series_id>', methods=['POST'])
def sim_playoff_series(series_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM league_playoff_series WHERE series_id = %s", (series_id,))
    series = cur.fetchone()
    league_id = series['league_id']
    
    while series['team1_wins'] < 4 and series['team2_wins'] < 4:
        cur.execute("SELECT game_id, home_team_id, away_team_id FROM league_schedule WHERE playoff_series_id = %s AND is_played = FALSE LIMIT 1", (series_id,))
        game = cur.fetchone()
        
        if not game:
            game_num = series['team1_wins'] + series['team2_wins'] + 1
            if game_num in [1, 2, 5, 7]: home, away = series['team1_id'], series['team2_id']
            else: home, away = series['team2_id'], series['team1_id']
            schedule_playoff_game(conn, league_id, series_id, home, away)
            
            # --- FIX: RE-FETCH GAME TO GET IDs ---
            cur.execute("SELECT game_id, home_team_id, away_team_id FROM league_schedule WHERE playoff_series_id = %s AND is_played = FALSE LIMIT 1", (series_id,))
            game = cur.fetchone()

        run_game_simulation(conn, league_id, game['game_id'], game['home_team_id'], game['away_team_id'])
        
        cur.execute("SELECT home_score, away_score FROM league_schedule WHERE game_id = %s", (game['game_id'],))
        res = cur.fetchone()
        game_winner_id = game['home_team_id'] if res['home_score'] > res['away_score'] else game['away_team_id']
        
        if game_winner_id == series['team1_id']: series['team1_wins'] += 1
        else: series['team2_wins'] += 1
            
        cur.execute("UPDATE league_playoff_series SET team1_wins=%s, team2_wins=%s WHERE series_id=%s", (series['team1_wins'], series['team2_wins'], series_id))
        conn.commit()

    winner_id = series['team1_id'] if series['team1_wins'] == 4 else series['team2_id']
    cur.execute("UPDATE league_playoff_series SET winner_team_id = %s WHERE series_id = %s", (winner_id, series_id))
    conn.commit()
    
    check_advance_round(conn, league_id, series['round_num'], series['conference'])
    
    cur.close()
    conn.close()
    return redirect(url_for('playoffs_view', league_id=league_id))

@app.route('/sim_single_playoff_game/<int:series_id>', methods=['POST'])
def sim_single_playoff_game(series_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM league_playoff_series WHERE series_id = %s", (series_id,))
    series = cur.fetchone()
    league_id = series['league_id']
    
    cur.execute("SELECT game_id, home_team_id, away_team_id FROM league_schedule WHERE playoff_series_id = %s AND is_played = FALSE LIMIT 1", (series_id,))
    game = cur.fetchone()
    
    if not game:
        game_num = series['team1_wins'] + series['team2_wins'] + 1
        if game_num in [1, 2, 5, 7]: home, away = series['team1_id'], series['team2_id']
        else: home, away = series['team2_id'], series['team1_id']
        schedule_playoff_game(conn, league_id, series_id, home, away)
        
        # --- FIX: RE-FETCH GAME ---
        cur.execute("SELECT game_id, home_team_id, away_team_id FROM league_schedule WHERE playoff_series_id = %s AND is_played = FALSE LIMIT 1", (series_id,))
        game = cur.fetchone()

    run_game_simulation(conn, league_id, game['game_id'], game['home_team_id'], game['away_team_id'])
    
    cur.execute("SELECT home_score, away_score FROM league_schedule WHERE game_id = %s", (game['game_id'],))
    res = cur.fetchone()
    winner_team_id = game['home_team_id'] if res['home_score'] > res['away_score'] else game['away_team_id']
    
    if winner_team_id == series['team1_id']: series['team1_wins'] += 1
    else: series['team2_wins'] += 1
        
    cur.execute("UPDATE league_playoff_series SET team1_wins=%s, team2_wins=%s WHERE series_id=%s", (series['team1_wins'], series['team2_wins'], series_id))
    
    if series['team1_wins'] == 4:
        cur.execute("UPDATE league_playoff_series SET winner_team_id=%s WHERE series_id=%s", (series['team1_id'], series_id))
        check_advance_round(conn, league_id, series['round_num'], series['conference'])
    elif series['team2_wins'] == 4:
        cur.execute("UPDATE league_playoff_series SET winner_team_id=%s WHERE series_id=%s", (series['team2_id'], series_id))
        check_advance_round(conn, league_id, series['round_num'], series['conference'])
        
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('playoffs_view', league_id=league_id))

def check_advance_round(conn, league_id, round_num, conference):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) as active FROM league_playoff_series WHERE league_id=%s AND round_num=%s AND conference=%s AND winner_team_id IS NULL", (league_id, round_num, conference))
    if cur.fetchone()['active'] == 0:
        cur.execute("SELECT series_id, winner_team_id FROM league_playoff_series WHERE league_id=%s AND round_num=%s AND conference=%s ORDER BY series_id ASC", (league_id, round_num, conference))
        results = cur.fetchall()
        
        if round_num == 1:
            create_series(conn, league_id, 2, conference, results[0]['winner_team_id'], results[1]['winner_team_id'])
            create_series(conn, league_id, 2, conference, results[2]['winner_team_id'], results[3]['winner_team_id'])
        elif round_num == 2:
            create_series(conn, league_id, 3, conference, results[0]['winner_team_id'], results[1]['winner_team_id'])
        elif round_num == 3:
            other_conf = 'East' if conference == 'West' else 'West'
            cur.execute("SELECT winner_team_id FROM league_playoff_series WHERE league_id=%s AND round_num=3 AND conference=%s", (league_id, other_conf))
            other_winner = cur.fetchone()
            if other_winner and other_winner['winner_team_id']:
                cur.execute("SELECT winner_team_id FROM league_playoff_series WHERE league_id=%s AND round_num=3 AND conference=%s", (league_id, conference))
                this_winner = cur.fetchone()
                create_series(conn, league_id, 4, 'Finals', this_winner['winner_team_id'], other_winner['winner_team_id'])
        elif round_num == 4:
            # --- CHAMPION CROWNED! ---
            cur.execute("SELECT season_year FROM leagues WHERE league_id=%s", (league_id,))
            season_year = cur.fetchone()['season_year']
            # The winner of the single Finals series
            champion_id = results[0]['winner_team_id']
            # Save History
            record_season_history(conn, league_id, season_year, champion_id)

def create_series(conn, league_id, round_num, conf, t1, t2):
    cur = conn.cursor()
    label = f"{conf} Round {round_num}" if conf != 'Finals' else "NBA Finals"
    cur.execute("INSERT INTO league_playoff_series (league_id, round_num, conference, team1_id, team2_id, series_label) VALUES (%s, %s, %s, %s, %s, %s) RETURNING series_id",
                (league_id, round_num, conf, t1, t2, label))
    sid = cur.fetchone()[0]
    schedule_playoff_game(conn, league_id, sid, t1, t2)
    conn.commit()

@app.route('/league_history/<int:league_id>')
def league_history(league_id):
    year = request.args.get('year') # Optional query param
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    
    # 1. Get available seasons
    cur.execute("SELECT DISTINCT season_year FROM league_season_history WHERE league_id = %s ORDER BY season_year DESC", (league_id,))
    seasons = cur.fetchall()
    
    selected_year = int(year) if year else (seasons[0]['season_year'] if seasons else league['season_year'])
    
    # 2. Get Standings for Selected Year
    cur.execute("""
        SELECT h.*, t.city, t.name, t.abbrev 
        FROM league_standings_history h
        JOIN league_teams t ON h.team_id = t.team_id
        WHERE h.league_id = %s AND h.season_year = %s
        ORDER BY h.wins DESC
    """, (league_id, selected_year))
    standings_raw = cur.fetchall()
    
    # 3. Get Champion for Selected Year
    cur.execute("""
        SELECT h.*, t.city, t.name, t.abbrev 
        FROM league_season_history h
        JOIN league_teams t ON h.champion_team_id = t.team_id
        WHERE h.league_id = %s AND h.season_year = %s
    """, (league_id, selected_year))
    champion = cur.fetchone()
    if champion: champion['logo_url'] = get_team_logo(champion['abbrev'])

    # Format Standings
    formatted_standings = {'East': [], 'West': []}
    for t in standings_raw:
        t['logo_url'] = get_team_logo(t['abbrev'])
        formatted_standings[t['conference']].append(t)
        
    cur.close()
    conn.close()
    return render_template('league_history.html', league=league, seasons=seasons, selected_year=selected_year, standings=formatted_standings, champion=champion)

@app.route('/champions_history/<int:league_id>')
def champions_history(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    
    cur.execute("""
        SELECT h.season_year, t.city, t.name, t.abbrev, t.team_id
        FROM league_season_history h
        JOIN league_teams t ON h.champion_team_id = t.team_id
        WHERE h.league_id = %s
        ORDER BY h.season_year DESC
    """, (league_id,))
    champs = cur.fetchall()
    
    for c in champs:
        c['logo_url'] = get_team_logo(c['abbrev'])
        
    cur.close()
    conn.close()
    return render_template('champions_history.html', league=league, champs=champs)

if __name__ == '__main__':
    app.run(debug=True)