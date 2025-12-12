from flask import Flask, request, redirect, url_for, render_template, session, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import defaultdict
import random
from simulation import run_game_simulation
import json
import calendar
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

# --- HELPER FUNCTIONS ---
def calculate_gb(leader_wins, leader_losses, team_wins, team_losses):
    if leader_wins is None: return 0
    diff = ((leader_wins - team_wins) + (team_losses - leader_losses)) / 2
    return diff if diff > 0 else 0

def calculate_playoff_odds(teams):
    # 1. Calculate Projections
    for t in teams:
        games_played = t['wins'] + t['losses']
        games_remaining = 82 - games_played
        win_pct = t['wins'] / games_played if games_played > 0 else 0.3
        t['projected_wins'] = t['wins'] + (games_remaining * win_pct)

    # 2. Sort by Projection
    sorted_teams = sorted(teams, key=lambda x: x['projected_wins'], reverse=True)
    cutoff_wins = sorted_teams[9]['projected_wins'] if len(sorted_teams) >= 10 else 35

    # 3. Assign Odds
    for t in teams:
        diff = t['projected_wins'] - cutoff_wins
        if diff >= 5: t['playoff_odds'] = 99.9
        elif diff >= 2: t['playoff_odds'] = 80 + (diff * 5)
        elif diff >= 0: t['playoff_odds'] = 50 + (diff * 10)
        elif diff > -5: t['playoff_odds'] = 50 - (abs(diff) * 10)
        else: t['playoff_odds'] = 0.1
        
        # Hard lock
        if t['wins'] > 46: t['playoff_odds'] = 100
        if t['losses'] > 50: t['playoff_odds'] = 0
        
        t['playoff_odds'] = "{:.1f}%".format(t['playoff_odds'])
    return teams

# --- LOGO HELPER ---
def get_team_logo(abbrev):
    # Normalize input
    abbrev = abbrev.upper().strip()
    
    # Map your database codes to ESPN's specific CDN codes
    mapping = {
        'UT': 'utah',   'UTA': 'utah',   'UTAH': 'utah',
        'BK': 'bkn',    'BKN': 'bkn',    'NETS': 'bkn',  'NJ': 'bkn',
        'OKL': 'okc',   'OKC': 'okc',    'THUNDER': 'okc',
        'NO': 'no',     'NOP': 'no',     'PELICANS': 'no', 'NOH': 'no',
        'GS': 'gsw',    'GSW': 'gsw',
        'NY': 'nyk',    'NYK': 'nyk',
        'SA': 'sas',    'SAS': 'sas',
        'PHX': 'phx',   'PHO': 'phx',
        'WAS': 'was',   'WSH': 'was',
    }
    code = mapping.get(abbrev, abbrev.lower())
    return f"https://a.espncdn.com/i/teamlogos/nba/500/{code}.png"

# ----- Free Agency Helper ---
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
    
    # Base Salary Scale
    if ovr >= 90: base = 45000000
    elif ovr >= 85: base = 30000000
    elif ovr >= 80: base = 20000000
    elif ovr >= 75: base = 12000000
    elif ovr >= 70: base = 5000000
    else: base = 1500000 # Minimum
    
    # Age Factor: Young potential costs more, old vets slightly less
    if age < 24: base *= 1.1
    if age > 33: base *= 0.8
    
    return int(base)

def attempt_ai_signings(conn, league_id):
    """Daily routine for AI teams to fill rosters"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Get League Cap
    cur.execute("SELECT salary_cap FROM leagues WHERE league_id = %s", (league_id,))
    cap = cur.fetchone()['salary_cap']
    
    # 2. Get AI Teams with roster spots (less than 15 players)
    cur.execute("""
        SELECT t.team_id, COUNT(p.player_id) as roster_count
        FROM league_teams t
        LEFT JOIN league_players p ON t.team_id = p.team_id
        WHERE t.league_id = %s
        GROUP BY t.team_id
        HAVING COUNT(p.player_id) < 14
    """, (league_id,))
    needy_teams = cur.fetchall()
    
    # 3. Get Top Free Agents
    cur.execute("SELECT * FROM league_players WHERE team_id IS NULL ORDER BY overall_rating DESC LIMIT 50")
    free_agents = cur.fetchall()
    
    for t in needy_teams:
        if random.random() > 0.3: continue # Don't sign every single day
        
        space, used = calculate_cap_space(conn, t['team_id'], cap)
        
        # Find best player they can afford
        for p in free_agents:
            asking = get_player_asking_price(p)
            if asking <= space:
                # SIGN HIM
                cur.execute("UPDATE league_players SET team_id = %s, salary_amount = %s WHERE player_id = %s", 
                            (t['team_id'], asking, p['player_id']))
                
                # Log Transaction
                desc = f"Signed Free Agent {p['first_name']} {p['last_name']} (${asking/1000000:.1f}M)"
                cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'signing')",
                            (league_id, t['team_id'], desc))
                
                conn.commit()
                # Remove from pool so other teams don't sign same guy in same loop
                free_agents.remove(p) 
                break


# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/load_league')
def load_league():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT league_id, name, season_year, sim_date, created_at 
        FROM leagues 
        ORDER BY created_at DESC
    """)
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

            if user_new_team_id:
                cur.execute("UPDATE leagues SET user_team_id = %s WHERE league_id = %s", (user_new_team_id, new_league_id))

            cur.execute("SELECT * FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = %s)", (scenario_id,))
            qs_players = cur.fetchall()
            for p in qs_players:
                new_team_id = id_map.get(p['qs_team_id'])
                if new_team_id:
                    cur.execute("""
                        INSERT INTO league_players (team_id, league_id, first_name, last_name, position, age, usage_rating, inside_shooting, outside_shooting, ft_shooting, passing, speed, guarding, stealing, blocking, rebounding, overall_rating, contract_years, salary_amount)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (new_team_id, new_league_id, p['first_name'], p['last_name'], p['position'], p['age'], p['usage_rating'], p['inside_shooting'], p['outside_shooting'], p['ft_shooting'], p['passing'], p['speed'], p['guarding'], p['stealing'], p['blocking'], p['rebounding'], p['overall_rating'], p['contract_years'], p['salary_amount']))

            cur.execute("SELECT * FROM quick_start_schedule WHERE scenario_id = %s", (scenario_id,))
            qs_games = cur.fetchall()
            for g in qs_games:
                new_home = id_map.get(g['home_qs_team_id'])
                new_away = id_map.get(g['away_qs_team_id'])
                cur.execute("""
                    INSERT INTO league_schedule (league_id, week_number, day_number, day_of_week, month_name, day_of_month, year, home_team_id, away_team_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (new_league_id, g['week_number'], g['day_number'], g['day_of_week'], g['month_name'], g['day_of_month'], g['year'], new_home, new_away))

            conn.commit()
            return redirect(url_for('league_dashboard', league_id=new_league_id))
        except Exception as e:
            conn.rollback()
            return f"Error: {str(e)}"
        finally:
            cur.close()
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
    sim_date = league['sim_date']

    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()

    cur.execute("SELECT * FROM league_teams WHERE league_id = %s ORDER BY wins DESC, losses ASC", (league_id,))
    teams = cur.fetchall()

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

    cur.execute("SELECT home_team_id, away_team_id, home_score, away_score FROM league_schedule WHERE league_id = %s AND is_played = TRUE ORDER BY game_id DESC", (league_id,))
    played_games = cur.fetchall()
    
    standings = defaultdict(lambda: defaultdict(list))
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
    
    for t in teams:
        t['logo_url'] = get_team_logo(t['abbrev'])

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

    # --- Calculate League Average EFF ---
    cur.execute("""
        SELECT 
            AVG(
                (COALESCE(SUM(b.points), 0) + COALESCE(SUM(b.rebounds), 0) + COALESCE(SUM(b.assists), 0) + 
                 COALESCE(SUM(b.steals), 0) + COALESCE(SUM(b.blocks), 0)) - 
                ((COALESCE(SUM(b.fg_attempts), 0) - COALESCE(SUM(b.fg_made), 0)) + 
                 (COALESCE(SUM(b.ft_attempts), 0) - COALESCE(SUM(b.ft_made), 0)) + 
                 COALESCE(SUM(b.turnovers), 0))
            ) / NULLIF(COUNT(b.game_id), 0) as avg_eff
        FROM league_players p
        JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.league_id = %s
        GROUP BY p.player_id
    """, (league_id,))
    
    all_effs = [row['avg_eff'] for row in cur.fetchall() if row['avg_eff'] is not None]
    league_avg_eff = sum(all_effs) / len(all_effs) if all_effs else 10.0

    cur.execute("""
        SELECT team_id, wins, losses,
        RANK() OVER (ORDER BY wins DESC, losses ASC) as rank
        FROM league_teams 
        WHERE league_id = %s AND conference = %s
    """, (league_id, team['conference']))
    rankings = cur.fetchall()
    team_rank = next((item['rank'] for item in rankings if item['team_id'] == team_id), "-")

    cur.execute("""
        SELECT p.*,
               COUNT(b.game_id) as gp,
               COALESCE(AVG(b.minutes), 0) as mpg,
               COALESCE(AVG(b.points), 0) as ppg,
               COALESCE(AVG(b.rebounds), 0) as rpg,
               COALESCE(AVG(b.assists), 0) as apg,
               COALESCE(AVG(b.steals), 0) as spg,
               COALESCE(AVG(b.blocks), 0) as bpg,
               COALESCE(AVG(b.plus_minus), 0) as pm,
               COALESCE(SUM(b.fg_attempts - b.fg_made), 0) as missed_fg,
               COALESCE(SUM(b.ft_attempts - b.ft_made), 0) as missed_ft,
               COALESCE(SUM(b.turnovers), 0) as total_tov,
               COALESCE(SUM(b.points + b.rebounds + b.assists + b.steals + b.blocks), 0) as positive_stats
        FROM league_players p
        LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.team_id = %s
        GROUP BY p.player_id
    """, (team_id,))
    roster = cur.fetchall()

    for p in roster:
        if p['gp'] > 0:
            total_eff = p['positive_stats'] - (p['missed_fg'] + p['missed_ft'] + p['total_tov'])
            eff_pg = total_eff / p['gp']
            # --- VAA Rounded to 0 digits ---
            p['vaa'] = "{:+.0f}".format(eff_pg - league_avg_eff)
            p['vaa_val'] = eff_pg - league_avg_eff
        else:
            p['vaa'] = "+0"
            p['vaa_val'] = -999

        p['ppg'] = "{:.1f}".format(p['ppg'])
        p['rpg'] = "{:.1f}".format(p['rpg'])
        p['apg'] = "{:.1f}".format(p['apg'])
        p['pm'] = "{:+.1f}".format(p['pm'])
        
        raw_salary = float(p['salary_amount'])
        p['salary_val'] = raw_salary
        p['salary_fmt'] = "${:.1f}M".format(raw_salary / 1000000.0)

    roster.sort(key=lambda x: x['vaa_val'], reverse=True)

    cur.close()
    conn.close()
    return render_template('team.html', team=team, league=league, all_leagues=all_leagues, roster=roster, rank=team_rank)

@app.route('/league_stats/<int:league_id>')
def league_stats(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Standard Info
    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()
    cur.execute("SELECT team_id, name, city, conference FROM league_teams WHERE league_id = %s ORDER BY city", (league_id,))
    teams = cur.fetchall()

    # 2. Fetch Aggregated Stats
    cur.execute("""
        SELECT 
            p.player_id, p.first_name, p.last_name, p.position, p.overall_rating, p.age,
            t.abbrev as team_abbrev, t.team_id, t.conference,
            COUNT(b.game_id) as gp,
            COALESCE(SUM(b.minutes), 0) as total_min,
            COALESCE(SUM(b.points), 0) as total_pts,
            COALESCE(SUM(b.rebounds), 0) as total_reb,
            COALESCE(SUM(b.assists), 0) as total_ast,
            COALESCE(SUM(b.steals), 0) as total_stl,
            COALESCE(SUM(b.blocks), 0) as total_blk,
            COALESCE(SUM(b.turnovers), 0) as total_tov,
            COALESCE(SUM(b.fg_made), 0) as total_fgm,
            COALESCE(SUM(b.fg_attempts), 0) as total_fga,
            COALESCE(SUM(b.threes_made), 0) as total_3pm,
            COALESCE(SUM(b.threes_attempts), 0) as total_3pa,
            COALESCE(SUM(b.ft_made), 0) as total_ftm,
            COALESCE(SUM(b.ft_attempts), 0) as total_fta
        FROM league_players p
        JOIN league_teams t ON p.team_id = t.team_id
        LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.league_id = %s
        GROUP BY p.player_id, t.team_id
    """, (league_id,))
    raw_stats = cur.fetchall()

    # 3. Process Stats
    active_effs = [] 
    stats = []
    
    for p in raw_stats:
        gp = p['gp']
        if gp > 0:
            # Efficiency Calculation
            missed_fg = p['total_fga'] - p['total_fgm']
            missed_ft = p['total_fta'] - p['total_ftm']
            raw_eff = (p['total_pts'] + p['total_reb'] + p['total_ast'] + p['total_stl'] + p['total_blk']) - (missed_fg + missed_ft + p['total_tov'])
            p['eff_per_game'] = raw_eff / gp
            active_effs.append(p['eff_per_game'])

            # Calculate Raw Averages
            p['mpg'] = p['total_min'] / gp
            p['ppg'] = p['total_pts'] / gp
            p['rpg'] = p['total_reb'] / gp
            p['apg'] = p['total_ast'] / gp
            p['spg'] = p['total_stl'] / gp
            p['bpg'] = p['total_blk'] / gp
        else:
            p['eff_per_game'] = 0
            p['mpg'] = 0; p['ppg'] = 0; p['rpg'] = 0
            p['apg'] = 0; p['spg'] = 0; p['bpg'] = 0

        # Formatting Averages (Round to 1 decimal)
        p['mpg_fmt'] = "{:.1f}".format(p['mpg'])
        p['ppg_fmt'] = "{:.1f}".format(p['ppg'])
        p['rpg_fmt'] = "{:.1f}".format(p['rpg'])
        p['apg_fmt'] = "{:.1f}".format(p['apg'])
        p['spg_fmt'] = "{:.1f}".format(p['spg'])
        p['bpg_fmt'] = "{:.1f}".format(p['bpg'])

        # Calculate & Format Percentages
        fg_pct = (p['total_fgm'] / p['total_fga'] * 100) if p['total_fga'] > 0 else 0.0
        three_pct = (p['total_3pm'] / p['total_3pa'] * 100) if p['total_3pa'] > 0 else 0.0
        ft_pct = (p['total_ftm'] / p['total_fta'] * 100) if p['total_fta'] > 0 else 0.0
        
        p['fg_pct_fmt'] = "{:.1f}%".format(fg_pct)
        p['three_pct_fmt'] = "{:.1f}%".format(three_pct)
        p['ft_pct_fmt'] = "{:.1f}%".format(ft_pct)
        
        stats.append(p)

    # 4. VAA Calculation
    league_avg_eff = sum(active_effs) / len(active_effs) if active_effs else 10.0

    for p in stats:
        if p['gp'] > 0:
            p['vaa'] = p['eff_per_game'] - league_avg_eff
        else:
            p['vaa'] = -league_avg_eff
            
        # Format VAA (Signed Integer)
        p['vaa_fmt'] = "{:+.0f}".format(p['vaa'])

    # 5. Sort by VAA
    stats.sort(key=lambda x: x['vaa'], reverse=True)

    cur.close()
    conn.close()
    
    return render_template('league_stats.html', league=league, all_leagues=all_leagues, stats=stats, teams=teams)

@app.route('/league_schedule/<int:league_id>')
def league_schedule(league_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM leagues WHERE league_id = %s", (league_id,))
    league = cur.fetchone()
    cur.execute("SELECT league_id, name FROM leagues ORDER BY created_at DESC")
    all_leagues = cur.fetchall()

    cur.execute("""
        SELECT s.*, 
               th.abbrev as home_abv, th.city as home_city, th.name as home_name,
               ta.abbrev as away_abv, ta.city as away_city, ta.name as away_name
        FROM league_schedule s
        JOIN league_teams th ON s.home_team_id = th.team_id
        JOIN league_teams ta ON s.away_team_id = ta.team_id
        WHERE s.league_id = %s
        ORDER BY s.year ASC, s.day_number ASC
    """, (league_id,))
    all_games = cur.fetchall()

    # --- NEW LOGIC: Pre-calculate date status ---
    import datetime
    sim_date = league['sim_date']
    
    # Map month names to numbers for date comparison
    month_map = {name: i for i, name in enumerate(calendar.month_name) if name}

    schedule_by_month = defaultdict(list)
    for g in all_games:
        # Add Logos
        g['home_logo'] = get_team_logo(g['home_abv'])
        g['away_logo'] = get_team_logo(g['away_abv'])
        
        # Clean data
        g_month = g['month_name'].strip()
        g_day = g['day_of_month']
        g_year = g['year']
        
        # Logic: Is this game today?
        # Compare components directly to avoid datetime parsing issues
        is_today = (g_day == sim_date.day and 
                    g_month == sim_date.strftime('%B') and 
                    g_year == sim_date.year)
        
        g['is_today'] = is_today
        
        # Logic: Postponed vs Upcoming
        # Create a date object for the game to compare accurately
        try:
            g_month_num = month_map.get(g_month, 1)
            game_date = datetime.date(g_year, g_month_num, g_day)
            
            if game_date < sim_date and not g['is_played']:
                g['status_label'] = 'Postponed'
            else:
                g['status_label'] = 'Upcoming'
        except:
            g['status_label'] = 'Upcoming' # Fallback
            
        key = f"{g['month_name']} {g['year']}"
        schedule_by_month[key].append(g)
    # --------------------------------------------

    cur.close()
    conn.close()
    return render_template('schedule.html', league=league, schedule_by_month=schedule_by_month, all_leagues=all_leagues)

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
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT sim_date FROM leagues WHERE league_id = %s", (league_id,))
    sim_date = cur.fetchone()['sim_date']
    
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
    
    for g in games:
        run_game_simulation(conn, league_id, g['game_id'], g['home_team_id'], g['away_team_id'])

    cur = conn.cursor()
    cur.execute("UPDATE leagues SET sim_date = sim_date + INTERVAL '1 day' WHERE league_id = %s", (league_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    if 'league_schedule' in request.referrer:
        return redirect(url_for('league_schedule', league_id=league_id))
    else:
        return redirect(url_for('league_dashboard', league_id=league_id))

@app.route('/boxscore/<int:game_id>')
def boxscore(game_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT s.*, 
               th.name as home_name, th.city as home_city, th.abbrev as home_abv,
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
        SELECT p.first_name, p.last_name, p.position, b.*
        FROM league_box_scores b
        JOIN league_players p ON b.player_id = p.player_id
        WHERE b.game_id = %s
        ORDER BY b.points DESC
    """, (game_id,))
    stats = cur.fetchall()
    
    home_stats = [s for s in stats if s['team_id'] == game['home_team_id']]
    away_stats = [s for s in stats if s['team_id'] == game['away_team_id']]
    
    cur.execute("SELECT * FROM league_game_events WHERE game_id = %s ORDER BY event_id ASC", (game_id,))
    pbp = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('boxscore.html', game=game, league=league, all_leagues=all_leagues, home_stats=home_stats, away_stats=away_stats, pbp=pbp)

@app.route('/strategy')
def coach_strategy():
    # 1. Get User's Team ID
    user_team_id = session.get('user_team_id', 61) 

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 2. Get the full LEAGUE object (Changed from just selecting name)
    cur.execute("""
        SELECT l.* FROM leagues l
        JOIN league_teams t ON t.league_id = l.league_id
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone() # This is now the full row, or None

    # 3. Fetch the Strategy
    cur.execute("SELECT * FROM coaching_strategy WHERE team_id = %s", (user_team_id,))
    strategy = cur.fetchone()

    # 4. If missing, create one
    if strategy is None:
        cur.execute("INSERT INTO coaching_strategy (team_id) VALUES (%s)", (user_team_id,))
        conn.commit()
        cur.execute("SELECT * FROM coaching_strategy WHERE team_id = %s", (user_team_id,))
        strategy = cur.fetchone()

    cur.close()
    conn.close()

    # 5. Pass 'league' to the template so base.html can see it
    return render_template('coach_strategy.html', strategy=strategy, league=league)

@app.route('/save_strategy', methods=['POST'])
def save_strategy():
    data = request.json
    user_team_id = session.get('user_team_id', 61) # Ensure this matches your login logic

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE coaching_strategy 
            SET offense_focus = %s,
                defense_focus = %s,
                bench_minutes = %s,
                rest_strategy = %s,
                training_focus = %s
            WHERE team_id = %s
        """, (
            data.get('offense_focus'),
            data.get('defense_focus'),
            data.get('bench_minutes'),
            data.get('rest_strategy'),
            data.get('training_focus'),
            user_team_id
        ))
        conn.commit()
        success = True
    except Exception as e:
        print(f"Error saving strategy: {e}")
        conn.rollback()
        success = False
    finally:
        cur.close()
        conn.close()

    return jsonify({'success': success})

@app.route('/rotation', methods=['GET', 'POST'])
def manage_rotation():
    # 1. Get User Context
    user_team_id = session.get('user_team_id', 61)
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 2. HANDLE SAVING (POST Request)
    if request.method == 'POST':
        try:
            # We expect a JSON list of player_ids in the desired order
            # Example: {'player_order': [101, 105, 120, ...]}
            data = request.json
            order_list = data.get('player_order', [])
            
            # Update each player's position in the rotation
            for index, player_id in enumerate(order_list):
                # index + 1 ensures the order starts at 1 (Starter) not 0
                cur.execute("""
                    UPDATE league_players 
                    SET rotation_order = %s 
                    WHERE player_id = %s AND team_id = %s
                """, (index + 1, player_id, user_team_id))
            
            conn.commit()
            return jsonify({'success': True})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'error': str(e)})
        finally:
            cur.close()
            conn.close()

    # 3. HANDLE VIEWING (GET Request)
    
    # Fetch League Info (for the header, same as Strategy page)
    cur.execute("""
        SELECT l.* FROM leagues l
        JOIN league_teams t ON t.league_id = l.league_id
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone()

    # Fetch Roster sorted by rotation_order first, then rating
    cur.execute("""
        SELECT player_id, first_name, last_name, position, 
               overall_rating, age, rotation_order
        FROM league_players 
        WHERE team_id = %s 
        ORDER BY rotation_order ASC, overall_rating DESC
    """, (user_team_id,))
    roster = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('rotation.html', league=league, roster=roster)

@app.route('/depth_chart', methods=['GET', 'POST'])
def depth_chart():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # --- SAVE REQUEST ---
    if request.method == 'POST':
        try:
            # Expecting data: { "player_ids": ["102", "55", "12"] }
            data = request.json
            player_ids = data.get('player_ids', [])
            
            # Update order in DB
            for index, pid in enumerate(player_ids):
                cur.execute("""
                    UPDATE league_players 
                    SET rotation_order = %s 
                    WHERE player_id = %s AND team_id = %s
                """, (index + 1, pid, user_team_id))
            
            conn.commit()
            return jsonify({'success': True})
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'error': str(e)})

    # --- VIEW REQUEST ---
    # 1. Get League Info for Header
    cur.execute("""
        SELECT l.* FROM leagues l
        JOIN league_teams t ON t.league_id = l.league_id
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone()

    # 2. Get Team Info for Header
    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (user_team_id,))
    team = cur.fetchone()
    team['logo_url'] = get_team_logo(team['abbrev'])

    # 3. Get Roster Sorted by Rotation Order
    cur.execute("""
        SELECT player_id, first_name, last_name, position, 
               overall_rating, age, rotation_order,
               usage_rating, contract_years, salary_amount
        FROM league_players 
        WHERE team_id = %s 
        ORDER BY rotation_order ASC, overall_rating DESC
    """, (user_team_id,))
    roster = cur.fetchall()

    cur.close()
    conn.close()
    
    return render_template('depth_chart.html', league=league, team=team, roster=roster)

@app.route('/my_team_stats')
def my_team_stats():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Get League & Team Info for Header
    cur.execute("""
        SELECT l.* FROM leagues l
        JOIN league_teams t ON t.league_id = l.league_id
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone()

    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (user_team_id,))
    team = cur.fetchone()
    team['logo_url'] = get_team_logo(team['abbrev'])

    # 2. Aggregated Stats Query (Filtered by Team)
    cur.execute("""
        SELECT 
            p.player_id, p.first_name, p.last_name, p.position, p.overall_rating, p.age,
            COUNT(b.game_id) as gp,
            COALESCE(SUM(b.minutes), 0) as total_min,
            COALESCE(SUM(b.points), 0) as total_pts,
            COALESCE(SUM(b.rebounds), 0) as total_reb,
            COALESCE(SUM(b.assists), 0) as total_ast,
            COALESCE(SUM(b.steals), 0) as total_stl,
            COALESCE(SUM(b.blocks), 0) as total_blk,
            COALESCE(SUM(b.turnovers), 0) as total_tov,
            COALESCE(SUM(b.fg_made), 0) as total_fgm,
            COALESCE(SUM(b.fg_attempts), 0) as total_fga,
            COALESCE(SUM(b.threes_made), 0) as total_3pm,
            COALESCE(SUM(b.threes_attempts), 0) as total_3pa,
            COALESCE(SUM(b.ft_made), 0) as total_ftm,
            COALESCE(SUM(b.ft_attempts), 0) as total_fta
        FROM league_players p
        LEFT JOIN league_box_scores b ON p.player_id = b.player_id
        WHERE p.team_id = %s
        GROUP BY p.player_id
    """, (user_team_id,))
    raw_stats = cur.fetchall()

    # 3. Calculate Averages & Percentages
    stats = []
    for p in raw_stats:
        gp = p['gp']
        if gp > 0:
            p['mpg'] = "{:.1f}".format(p['total_min'] / gp)
            p['ppg'] = "{:.1f}".format(p['total_pts'] / gp)
            p['rpg'] = "{:.1f}".format(p['total_reb'] / gp)
            p['apg'] = "{:.1f}".format(p['total_ast'] / gp)
            p['spg'] = "{:.1f}".format(p['total_stl'] / gp)
            p['bpg'] = "{:.1f}".format(p['total_blk'] / gp)
            p['tov'] = "{:.1f}".format(p['total_tov'] / gp)
            
            # Shooting Percentages
            p['fg_pct'] = (p['total_fgm'] / p['total_fga'] * 100) if p['total_fga'] > 0 else 0.0
            p['fg_pct_fmt'] = "{:.1f}%".format(p['fg_pct'])

            p['three_pct'] = (p['total_3pm'] / p['total_3pa'] * 100) if p['total_3pa'] > 0 else 0.0
            p['three_pct_fmt'] = "{:.1f}%".format(p['three_pct'])

            p['ft_pct'] = (p['total_ftm'] / p['total_fta'] * 100) if p['total_fta'] > 0 else 0.0
            p['ft_pct_fmt'] = "{:.1f}%".format(p['ft_pct'])
        else:
            p['mpg'] = "0.0"; p['ppg'] = "0.0"; p['rpg'] = "0.0"
            p['apg'] = "0.0"; p['spg'] = "0.0"; p['bpg'] = "0.0"; p['tov'] = "0.0"
            p['fg_pct_fmt'] = "-"; p['three_pct_fmt'] = "-"; p['ft_pct_fmt'] = "-"
            p['fg_pct'] = 0; p['three_pct'] = 0; p['ft_pct'] = 0

        stats.append(p)

    # Sort by PPG by default
    stats.sort(key=lambda x: float(x['ppg']), reverse=True)

    cur.close()
    conn.close()
    return render_template('team_stats.html', league=league, team=team, stats=stats)

# --- TRADE HELPER FUNCTIONS ---
def get_player_trade_value(player):
    """Calculates a trade value score (0-100+)"""
    ovr = player['overall_rating']
    age = player['age']
    contract_yrs = player['contract_years']
    
    # Base Value is essentially the rating
    value = ovr
    
    # Age penalty/bonus
    if age < 24: value += 5
    if age > 32: value -= (age - 32) * 2
    
    # Contract status (Expiring contracts have value, bad long contracts hurt)
    if contract_yrs > 2 and age > 30: value -= 5
    
    # SUPERSTAR PREMIUM (The "Hesitation" Logic)
    # Players 90+ are exponentially more valuable.
    # A 95 is not just 5 points better than a 90; they are franchise changers.
    if ovr >= 90: value *= 1.5 
    elif ovr >= 85: value *= 1.2
    
    return int(value)

def get_pick_trade_value(pick, team_record):
    """Calculates pick value based on original owner's win %"""
    # Inverse of win pct: Bad teams = Higher Pick Value
    win_pct = team_record['wins'] / (team_record['wins'] + team_record['losses']) if (team_record['wins'] + team_record['losses']) > 0 else 0.5
    projected_rank = 100 - (win_pct * 100) # Simple projection
    
    if pick['round'] == 1:
        return 20 + (projected_rank * 0.8) # 1st rounders worth 20-100 points
    else:
        return 5 + (projected_rank * 0.1)  # 2nd rounders worth 5-15 points

@app.route('/trade_block', methods=['GET'])
def trade_block():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get League Info
    cur.execute("""
        SELECT l.* FROM leagues l
        JOIN league_teams t ON t.league_id = l.league_id
        WHERE t.team_id = %s
    """, (user_team_id,))
    league = cur.fetchone()

    # Get User Team
    cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (user_team_id,))
    user_team = cur.fetchone()
    user_team['logo_url'] = get_team_logo(user_team['abbrev'])

    # Get User Assets (Players)
    cur.execute("SELECT * FROM league_players WHERE team_id = %s ORDER BY overall_rating DESC", (user_team_id,))
    user_players = cur.fetchall()
    
    # Get User Assets (Picks)
    cur.execute("""
        SELECT p.*, t.abbrev as original_owner 
        FROM league_draft_picks p
        JOIN league_teams t ON p.original_team_id = t.team_id
        WHERE p.owner_team_id = %s
    """, (user_team_id,))
    user_picks = cur.fetchall()

    # Get All Other Teams for Dropdown
    cur.execute("SELECT * FROM league_teams WHERE league_id = %s AND team_id != %s ORDER BY city", (league['league_id'], user_team_id))
    other_teams = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('trade_block.html', league=league, user_team=user_team, user_players=user_players, user_picks=user_picks, other_teams=other_teams)

@app.route('/get_team_assets/<int:team_id>')
def get_team_assets(team_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch Players
    cur.execute("SELECT player_id, first_name, last_name, position, overall_rating, age, salary_amount FROM league_players WHERE team_id = %s ORDER BY overall_rating DESC", (team_id,))
    players = cur.fetchall()
    
    # Fetch Picks
    cur.execute("""
        SELECT p.*, t.abbrev as original_owner 
        FROM league_draft_picks p
        JOIN league_teams t ON p.original_team_id = t.team_id
        WHERE p.owner_team_id = %s
    """, (team_id,))
    picks = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # Convert decimals for JSON
    for p in players:
        p['salary_amount'] = float(p['salary_amount'])
        p['formatted_salary'] = "${:.1f}M".format(p['salary_amount']/1000000)

    return jsonify({'players': players, 'picks': picks})

@app.route('/propose_trade', methods=['POST'])
def propose_trade():
    data = request.json
    user_assets = data.get('user_assets', [])
    partner_assets = data.get('partner_assets', [])
    partner_team_id = data.get('partner_team_id')
    
    if len(user_assets) > 3 or len(partner_assets) > 3:
        return jsonify({'success': False, 'message': 'Maximum 3 assets per side allowed.'})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Calculate Values & Salaries
    user_total_value = 0
    partner_total_value = 0
    
    user_salary_out = 0
    partner_salary_out = 0
    
    # -- Process User Side --
    for asset in user_assets:
        if asset['type'] == 'player':
            cur.execute("SELECT * FROM league_players WHERE player_id = %s", (asset['id'],))
            p = cur.fetchone()
            val = get_player_trade_value(p)
            user_total_value += val
            user_salary_out += float(p['salary_amount'])
        elif asset['type'] == 'pick':
            cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (asset['original_team_id'],))
            t_record = cur.fetchone()
            # If no record found (start of game), assume .500
            if not t_record: t_record = {'wins': 0, 'losses': 0}
            
            cur.execute("SELECT * FROM league_draft_picks WHERE pick_id = %s", (asset['id'],))
            pick = cur.fetchone()
            
            val = get_pick_trade_value(pick, t_record)
            user_total_value += val

    # -- Process Partner Side --
    max_partner_player_ovr = 0
    
    for asset in partner_assets:
        if asset['type'] == 'player':
            cur.execute("SELECT * FROM league_players WHERE player_id = %s", (asset['id'],))
            p = cur.fetchone()
            val = get_player_trade_value(p)
            partner_total_value += val
            partner_salary_out += float(p['salary_amount'])
            
            if p['overall_rating'] > max_partner_player_ovr:
                max_partner_player_ovr = p['overall_rating']
                
        elif asset['type'] == 'pick':
            cur.execute("SELECT * FROM league_teams WHERE team_id = %s", (asset['original_team_id'],))
            t_record = cur.fetchone()
            cur.execute("SELECT * FROM league_draft_picks WHERE pick_id = %s", (asset['id'],))
            pick = cur.fetchone()
            val = get_pick_trade_value(pick, t_record)
            partner_total_value += val

    # 2. Salary Matching Logic (Standard NBA: within 125% + 100k, simplified here to 20%)
    # Only applies if salaries are high (> $10M)
    salary_diff_ratio = 1.0
    if user_salary_out > 10000000 or partner_salary_out > 10000000:
        if partner_salary_out > 0:
            salary_diff_ratio = user_salary_out / partner_salary_out
    
    salary_match = 0.8 <= salary_diff_ratio <= 1.25

    # 3. Decision Logic
    decision = "rejected"
    message = "The other team is not interested."
    
    # Logic: Superstar Hesitation
    threshold = 1.0
    if max_partner_player_ovr >= 90:
        threshold = 1.4
        message = "They are hesitant to move a superstar for this package."
    elif max_partner_player_ovr >= 85:
        threshold = 1.2
        message = "They value their star player highly."

    # Compare Values & Execute
    if not salary_match:
        decision = "rejected"
        message = "Salaries do not match. (Must be within 20%)"
    elif user_total_value >= (partner_total_value * threshold):
        decision = "accepted"
        message = "Trade Accepted!"
        
        # --- FIX: Ensure user_team_id has a default value (61) ---
        user_team_id = session.get('user_team_id', 61)
        
        # 1. Move User Assets -> Partner
        for asset in user_assets:
            if asset['type'] == 'player':
                cur.execute("UPDATE league_players SET team_id = %s WHERE player_id = %s", (partner_team_id, asset['id']))
            elif asset['type'] == 'pick':
                cur.execute("UPDATE league_draft_picks SET owner_team_id = %s WHERE pick_id = %s", (partner_team_id, asset['id']))

        # 2. Move Partner Assets -> User
        for asset in partner_assets:
            if asset['type'] == 'player':
                # This was previously setting team_id to None because session might be empty
                cur.execute("UPDATE league_players SET team_id = %s WHERE player_id = %s", (user_team_id, asset['id']))
            elif asset['type'] == 'pick':
                cur.execute("UPDATE league_draft_picks SET owner_team_id = %s WHERE pick_id = %s", (user_team_id, asset['id']))

        conn.commit()

    else:
        # Provide specific feedback
        shortfall = int((partner_total_value * threshold) - user_total_value)
        message = f"Offer too low. They need more value (Gap: {shortfall} pts)."

    cur.close()
    conn.close()
    
    return jsonify({
        'decision': decision,
        'message': message,
        'user_val': user_total_value,
        'partner_val': int(partner_total_value * threshold)
    })

@app.route('/free_agency')
def free_agency():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # League & Team Info
    cur.execute("SELECT * FROM leagues l JOIN league_teams t ON l.league_id=t.league_id WHERE t.team_id=%s", (user_team_id,))
    league = cur.fetchone()
    
    # Calculate Cap Space
    cap_space, used_cap = calculate_cap_space(conn, user_team_id, league['salary_cap'])
    
    # Fetch Free Agents
    cur.execute("""
        SELECT * FROM league_players 
        WHERE team_id IS NULL 
        ORDER BY overall_rating DESC
    """)
    free_agents = cur.fetchall()
    
    # Calculate "Asking Price" for display (Hidden guide for user)
    for p in free_agents:
        p['asking_price'] = get_player_asking_price(p)
    
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
    
    # Check Cap Space
    cur.execute("SELECT salary_cap, league_id FROM leagues WHERE league_id = (SELECT league_id FROM league_teams WHERE team_id=%s)", (user_team_id,))
    row = cur.fetchone()
    salary_cap = row['salary_cap']
    league_id = row['league_id']
    
    space, used = calculate_cap_space(conn, user_team_id, salary_cap)
    
    if offer_amount > space:
        return jsonify({'decision': 'error', 'message': 'You do not have enough cap space!'})

    # Agent Logic
    cur.execute("SELECT * FROM league_players WHERE player_id = %s", (player_id,))
    player = cur.fetchone()
    asking_price = get_player_asking_price(player)
    
    ratio = offer_amount / asking_price
    
    decision = "reject"
    message = "The agent hangs up the phone."
    
    if ratio >= 1.0:
        decision = "accepted"
        message = "Deal! The player is excited to join."
        
        # Execute Signing
        cur.execute("UPDATE league_players SET team_id = %s, salary_amount = %s WHERE player_id = %s", (user_team_id, offer_amount, player_id))
        
        # Log Transaction
        desc = f"Signed {player['first_name']} {player['last_name']} for ${offer_amount/1000000:.2f}M"
        cur.execute("INSERT INTO league_transactions (league_id, team_id, description, transaction_type) VALUES (%s, %s, %s, 'signing')", 
                    (league_id, user_team_id, desc))
        conn.commit()
        
    elif ratio >= 0.85:
        decision = "counter"
        counter_offer = int(asking_price * 0.95) # They meet you halfway
        message = f"Close, but not enough. We would accept ${counter_offer/1000000:.2f}M."
    else:
        decision = "insulted"
        message = "That offer is insulting for a player of his caliber."

    cur.close()
    conn.close()
    
    return jsonify({
        'decision': decision, 
        'message': message, 
        'likelihood': int(min(ratio * 100, 100)) # Return interest %
    })

@app.route('/transactions')
def transactions():
    user_team_id = session.get('user_team_id', 61)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch League ID
    cur.execute("SELECT league_id FROM league_teams WHERE team_id=%s", (user_team_id,))
    league_id = cur.fetchone()['league_id']
    
    cur.execute("SELECT * FROM leagues WHERE league_id=%s", (league_id,))
    league = cur.fetchone()

    # Fetch Transactions
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

if __name__ == '__main__':
    app.run(debug=True)