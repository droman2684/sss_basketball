import random

# ---------------------------------------------------------
# GENERATE REALISTIC NBA ROSTERS
# ---------------------------------------------------------
# Creates 12-15 players per team with realistic ratings

positions = ['PG', 'SG', 'SF', 'PF', 'C']

# Sample first/last names for variety
first_names = [
    'James', 'Kevin', 'Stephen', 'LeBron', 'Anthony', 'Chris', 'Russell', 'Damian',
    'Joel', 'Giannis', 'Luka', 'Jayson', 'Devin', 'Nikola', 'Kawhi', 'Jimmy',
    'Kyrie', 'Paul', 'Draymond', 'Klay', 'Jrue', 'Khris', 'Bradley', 'De',
    'DeMar', 'Kyle', 'Pascal', 'Fred', 'Marcus', 'Derrick', 'Zach', 'Lonzo',
    'Trae', 'Donovan', 'Rudy', 'Karl-Anthony', 'D\'Angelo', 'Brandon', 'Julius',
    'Bam', 'Tyler', 'Ben', 'Tobias', 'CJ', 'Darius', 'Shai', 'Dejounte', 'Jordan'
]

last_names = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Davis', 'Miller', 'Wilson', 'Moore',
    'Taylor', 'Anderson', 'Thomas', 'Jackson', 'White', 'Harris', 'Martin', 'Thompson',
    'Garcia', 'Martinez', 'Robinson', 'Clark', 'Rodriguez', 'Lewis', 'Lee', 'Walker',
    'Hall', 'Allen', 'Young', 'King', 'Wright', 'Lopez', 'Hill', 'Scott', 'Green',
    'Adams', 'Baker', 'Nelson', 'Carter', 'Mitchell', 'Roberts', 'Turner', 'Phillips',
    'Campbell', 'Parker', 'Evans', 'Edwards', 'Collins', 'Stewart', 'Morris', 'Rogers'
]

sql_lines = []
sql_lines.append("-- AUTO-GENERATED ROSTERS")
sql_lines.append("-- Generated with balanced rosters (Stars, Role Players, Bench)")
sql_lines.append("DELETE FROM quick_start_players WHERE qs_team_id IN (SELECT qs_team_id FROM quick_start_teams WHERE scenario_id = 1);")
sql_lines.append("")

# Generate roster for each of 30 teams
for team_id in range(1, 31):
    roster_size = random.randint(12, 15)  # Random roster size

    print(f"Generating roster for Team {team_id} ({roster_size} players)...")

    for i in range(roster_size):
        # Position rotation (ensures good position balance)
        pos = positions[i % 5]

        # Random name
        first = random.choice(first_names)
        last = random.choice(last_names)

        # Age distribution
        if i < 3:
            age = random.randint(25, 30)  # Prime years for stars
        elif i < 8:
            age = random.randint(23, 32)  # Mixed for starters/role players
        else:
            age = random.randint(20, 35)  # Wide range for bench

        # ===== RATING TIERS =====
        # Top 3: Stars (82-95 overall)
        if i < 3:
            overall = random.randint(82, 95)
            salary = random.randint(25_000_000, 45_000_000)
            contract_years = random.randint(3, 5)
        # Next 4-5: Starters/Key Role Players (72-82)
        elif i < 7:
            overall = random.randint(72, 82)
            salary = random.randint(10_000_000, 25_000_000)
            contract_years = random.randint(2, 4)
        # Rest: Bench/Role Players (60-72)
        else:
            overall = random.randint(60, 72)
            salary = random.randint(1_500_000, 10_000_000)
            contract_years = random.randint(1, 3)

        # ===== ATTRIBUTE GENERATION =====
        # All attributes are based on overall rating with some variance

        usage = max(20, min(100, overall - random.randint(5, 15)))

        # Shooting stats (vary by position)
        if pos in ['PG', 'SG', 'SF']:
            # Guards/Wings: Better outside shooting
            inside = max(30, min(100, overall + random.randint(-15, 5)))
            outside = max(30, min(100, overall + random.randint(-5, 15)))
        else:
            # Bigs: Better inside shooting
            inside = max(30, min(100, overall + random.randint(-5, 15)))
            outside = max(30, min(100, overall + random.randint(-15, 5)))

        ft_rating = max(40, min(100, overall + random.randint(-10, 10)))

        # Playmaking (PGs get boost)
        if pos == 'PG':
            passing = max(40, min(100, overall + random.randint(0, 15)))
        else:
            passing = max(30, min(100, overall + random.randint(-10, 10)))

        # Speed (Guards faster)
        if pos in ['PG', 'SG']:
            speed = max(40, min(100, overall + random.randint(-5, 15)))
        else:
            speed = max(30, min(100, overall + random.randint(-10, 5)))

        # Defense
        guarding = max(30, min(100, overall + random.randint(-10, 10)))
        stealing = max(30, min(100, overall + random.randint(-10, 10)))

        # Rim protection (Centers get boost)
        if pos == 'C':
            blocking = max(40, min(100, overall + random.randint(0, 15)))
        elif pos == 'PF':
            blocking = max(35, min(100, overall + random.randint(-5, 10)))
        else:
            blocking = max(25, min(100, overall + random.randint(-15, 5)))

        # Rebounding (Bigs get boost)
        if pos in ['C', 'PF']:
            rebounding = max(40, min(100, overall + random.randint(0, 15)))
        else:
            rebounding = max(30, min(100, overall + random.randint(-10, 5)))

        # ===== GENERATE SQL INSERT =====
        values = (
            team_id,           # qs_team_id
            first,             # first_name
            last,              # last_name
            pos,               # position
            age,               # age
            usage,             # usage_rating
            inside,            # inside_shooting
            outside,           # outside_shooting
            ft_rating,         # ft_shooting
            passing,           # passing
            speed,             # speed
            guarding,          # guarding
            stealing,          # stealing
            blocking,          # blocking
            rebounding,        # rebounding
            overall,           # overall_rating
            contract_years,    # contract_years
            salary             # salary_amount
        )

        sql = f"INSERT INTO quick_start_players (qs_team_id, first_name, last_name, position, age, usage_rating, inside_shooting, outside_shooting, ft_shooting, passing, speed, guarding, stealing, blocking, rebounding, overall_rating, contract_years, salary_amount) VALUES ({team_id}, '{first}', '{last}', '{pos}', {age}, {usage}, {inside}, {outside}, {ft_rating}, {passing}, {speed}, {guarding}, {stealing}, {blocking}, {rebounding}, {overall}, {contract_years}, {salary});"

        sql_lines.append(sql)

# ---------------------------------------------------------
# WRITE TO FILE
# ---------------------------------------------------------
output_file = 'populate_rosters.sql'
with open(output_file, 'w') as f:
    f.write("\n".join(sql_lines))

print(f"\nSuccess! Rosters created at: {output_file}")
print(f"Total Players Generated: {sum(random.randint(12, 15) for _ in range(30))} (approx 390-450)")
print("\nTo populate your database, run:")
print(f"  psql -d your_database -f {output_file}")
print("  OR copy/paste the SQL into pgAdmin")
