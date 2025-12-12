from dotenv import load_dotenv
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import random
import calendar
from datetime import date

load_dotenv()

conn = psycopg2.connect(
    dbname=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    host=os.getenv('DB_HOST'),
    sslmode='require'
)

cur = conn.cursor(cursor_factory=RealDictCursor)

print("=== POPULATING QUICK START DATA ===\n")

# ========================================
# 1. POPULATE PLAYERS FROM EXCEL
# ========================================
print("Step 1: Importing players from Excel...")

try:
    df = pd.read_excel('2024 Players.xlsx')
    print(f"  Found {len(df)} players in Excel file")

    # Clear existing players
    cur.execute("DELETE FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = 1)")

    # Get team mapping
    cur.execute("SELECT qs_team_id, abbrev FROM quick_start_teams WHERE scenario_id = 1")
    teams = {t['abbrev'].upper(): t['qs_team_id'] for t in cur.fetchall()}

    imported = 0
    for idx, row in df.iterrows():
        # Map team abbreviation
        team_abbrev = str(row.get('Team', '')).strip().upper()
        qs_team_id = teams.get(team_abbrev)

        if not qs_team_id:
            print(f"  Warning: Unknown team '{team_abbrev}' for player {row.get('Player', 'Unknown')}")
            continue

        # Extract player data
        first_name = str(row.get('First Name', '')).strip()
        last_name = str(row.get('Last Name', '')).strip()
        position = str(row.get('Pos', 'G')).strip()
        age = int(row.get('Age', 25))

        # Ratings
        usage = int(row.get('Usage', 50))
        inside = int(row.get('Inside', 50))
        outside = int(row.get('Outside', 50))
        ft = int(row.get('FT', 75))
        passing = int(row.get('Passing', 50))
        speed = int(row.get('Speed', 50))
        guarding = int(row.get('Defense', 50))
        stealing = int(row.get('Steals', 50))
        blocking = int(row.get('Blocks', 50))
        rebounding = int(row.get('Rebounds', 50))
        overall = int(row.get('Overall', 70))

        # Contract
        contract_years = int(row.get('Contract Years', 2))
        salary = int(row.get('Salary', 5000000))

        cur.execute("""
            INSERT INTO quick_start_players
            (qs_team_id, first_name, last_name, position, age, usage_rating,
             inside_shooting, outside_shooting, ft_shooting, passing, speed,
             guarding, stealing, blocking, rebounding, overall_rating,
             contract_years, salary_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (qs_team_id, first_name, last_name, position, age, usage,
              inside, outside, ft, passing, speed, guarding, stealing,
              blocking, rebounding, overall, contract_years, salary))

        imported += 1

    print(f"  ✓ Imported {imported} players!")

except FileNotFoundError:
    print("  ⚠️  2024 Players.xlsx not found. Creating sample players instead...")

    # Create sample players for each team
    cur.execute("SELECT qs_team_id, abbrev, city, name FROM quick_start_teams WHERE scenario_id = 1")
    teams = cur.fetchall()

    positions = ['PG', 'SG', 'SF', 'PF', 'C']
    first_names = ['James', 'Kevin', 'Stephen', 'LeBron', 'Anthony', 'Chris', 'Russell', 'Damian', 'Joel', 'Giannis', 'Luka', 'Jayson', 'Devin', 'Nikola', 'Kawhi']
    last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Davis', 'Miller', 'Wilson', 'Moore', 'Taylor', 'Anderson', 'Thomas', 'Jackson', 'White', 'Harris', 'Martin']

    imported = 0
    for team in teams:
        # Create 12-15 players per team
        roster_size = random.randint(12, 15)

        for i in range(roster_size):
            pos = positions[i % 5]
            first = random.choice(first_names)
            last = random.choice(last_names)
            age = random.randint(20, 35)

            # Stars (top 3 players have higher ratings)
            if i < 3:
                overall = random.randint(82, 95)
                salary = random.randint(25000000, 45000000)
            elif i < 7:
                overall = random.randint(72, 82)
                salary = random.randint(10000000, 25000000)
            else:
                overall = random.randint(60, 72)
                salary = random.randint(2000000, 10000000)

            # Generate other ratings based on overall
            usage = overall - random.randint(5, 15)
            inside = overall + random.randint(-10, 10)
            outside = overall + random.randint(-10, 10)
            ft_rating = overall + random.randint(-5, 10)
            defense = overall + random.randint(-8, 8)

            cur.execute("""
                INSERT INTO quick_start_players
                (qs_team_id, first_name, last_name, position, age, usage_rating,
                 inside_shooting, outside_shooting, ft_shooting, passing, speed,
                 guarding, stealing, blocking, rebounding, overall_rating,
                 contract_years, salary_amount)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (team['qs_team_id'], first, last, pos, age, usage,
                  inside, outside, ft_rating, defense, defense, defense,
                  defense, defense, defense, overall,
                  random.randint(1, 4), salary))

            imported += 1

    print(f"  ✓ Created {imported} sample players!")

conn.commit()

# ========================================
# 2. GENERATE SCHEDULE
# ========================================
print("\nStep 2: Generating 82-game schedule...")

# Clear existing schedule
cur.execute("DELETE FROM quick_start_schedule WHERE scenario_id = 1")

# Get all teams
cur.execute("SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = 1 ORDER BY qs_team_id")
teams = [t['qs_team_id'] for t in cur.fetchall()]

if len(teams) != 30:
    print(f"  Error: Expected 30 teams, found {len(teams)}")
else:
    # Generate matchups
    matchups = []

    # Each team plays every other team 2 times (home and away) = 58 games
    for t1 in teams:
        for t2 in teams:
            if t1 != t2:
                matchups.append((t1, t2))  # t1 home, t2 away

    # Additional games to reach 82 per team
    # We need 24 more games per team (30 teams * 24 / 2 = 360 additional games)
    additional_needed = 360
    for _ in range(additional_needed):
        t1 = random.choice(teams)
        t2 = random.choice([t for t in teams if t != t1])
        matchups.append((t1, t2))

    # Shuffle for randomness
    random.shuffle(matchups)

    # Schedule games across the season
    # NBA season: Late October to Early April (~175 days)
    start_date = date(2024, 10, 22)  # October 22, 2024

    game_day = 0
    week_num = 1

    for idx, (home_id, away_id) in enumerate(matchups):
        # Distribute games (3-4 games per day on average)
        if idx % 10 == 0:
            game_day += 1

        # Calculate actual date
        from datetime import timedelta
        game_date = start_date + timedelta(days=game_day)

        month_name = game_date.strftime('%B')
        day_of_month = game_date.day
        year = game_date.year
        day_of_week = game_date.strftime('%A')

        # Week number
        week_num = (game_day // 7) + 1
        day_number = game_day + 1

        cur.execute("""
            INSERT INTO quick_start_schedule
            (scenario_id, week_number, day_number, day_of_week, month_name,
             day_of_month, year, home_qs_team_id, away_qs_team_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (1, week_num, day_number, day_of_week, month_name,
              day_of_month, year, home_id, away_id))

    print(f"  ✓ Created {len(matchups)} games across {game_day} days!")

conn.commit()

# ========================================
# 3. VERIFY
# ========================================
print("\nStep 3: Verification...")

cur.execute("SELECT COUNT(*) as count FROM quick_start_players")
player_count = cur.fetchone()['count']
print(f"  Total Players: {player_count}")

cur.execute("SELECT COUNT(*) as count FROM quick_start_schedule")
game_count = cur.fetchone()['count']
print(f"  Total Games: {game_count}")

# Verify games per team
cur.execute("""
    SELECT home_qs_team_id as team_id, COUNT(*) as home_games
    FROM quick_start_schedule
    WHERE scenario_id = 1
    GROUP BY home_qs_team_id
""")
home_games = {row['team_id']: row['home_games'] for row in cur.fetchall()}

cur.execute("""
    SELECT away_qs_team_id as team_id, COUNT(*) as away_games
    FROM quick_start_schedule
    WHERE scenario_id = 1
    GROUP BY away_qs_team_id
""")
away_games = {row['team_id']: row['away_games'] for row in cur.fetchall()}

print(f"\n  Games per team:")
for team_id in sorted(teams)[:5]:  # Show first 5
    total = home_games.get(team_id, 0) + away_games.get(team_id, 0)
    print(f"    Team {team_id}: {total} games ({home_games.get(team_id, 0)} home, {away_games.get(team_id, 0)} away)")

conn.close()

print("\n✓ QUICK START DATA POPULATED SUCCESSFULLY!")
print("\nYou can now create a new league and it will automatically:")
print("  - Have all 30 teams with rosters")
print("  - Have a full 82-game schedule")
print("  - Be ready to simulate!")
