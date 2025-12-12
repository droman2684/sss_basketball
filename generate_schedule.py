import random
import datetime

# 1. Define Teams (IDs 1-30)
teams = list(range(1, 31))

# ---------------------------------------------------------
# 2. GENERATE MATCHUPS (1230 Total Games / 82 per team)
# ---------------------------------------------------------
matchups = []

# A. Round Robin: Everyone plays everyone twice (Home & Away)
# 30 teams * 29 opponents = 870 games
for t1 in teams:
    for t2 in teams:
        if t1 != t2:
            matchups.append((t1, t2))

# B. Fill remaining games to reach 82 per team
# We need 360 more games (1230 total - 870 existing).
# We add 12 extra games per team (6 home, 6 away against randoms).
extra_games_per_team = 12
for _ in range(extra_games_per_team // 2): # Divide by 2 because adding a pair adds 1 game for TWO teams
    random.shuffle(teams)
    # Pair them up: (Team 0 vs Team 1), (Team 2 vs Team 3), etc.
    for k in range(0, 30, 2):
        t1 = teams[k]
        t2 = teams[k+1]
        # Randomize home/away for these extras
        if random.random() > 0.5:
            matchups.append((t1, t2))
        else:
            matchups.append((t2, t1))

# Shuffle the entire pool so the season isn't ordered by ID
random.shuffle(matchups)

# ---------------------------------------------------------
# 3. ASSIGN DATES (The "Bucket" Logic)
# ---------------------------------------------------------
start_date = datetime.date(2024, 10, 22)
end_date_limit = datetime.date(2025, 6, 1) # Just a safety backstop
current_date = start_date

sql_lines = []
sql_lines.append("-- SCHEDULE TEMPLATE (2024-25 Balanced)")
sql_lines.append("DELETE FROM quick_start_schedule;") 

# We will process the 'matchups' list until it is empty.
# On each "Game Day", we try to schedule as many games as possible (max 15)
# without repeating a team.
game_queue = matchups[:] # Copy of list

while len(game_queue) > 0 and current_date < end_date_limit:
    
    # --- Check All-Star Break ---
    # If we hit Feb 14, jump to Feb 20
    if current_date == datetime.date(2025, 2, 14):
        current_date = datetime.date(2025, 2, 20)

    # --- Daily Scheduling ---
    todays_games = []
    teams_playing_today = set()
    
    # Temporary list for games we can't schedule today (because teams are busy)
    next_queue = []
    
    # Iterate through the queue and grab valid games for today
    for home, away in game_queue:
        # If we have 15 games, the day is full (all 30 teams playing)
        if len(todays_games) >= 15:
            next_queue.append((home, away))
            continue
            
        # Check if teams are already booked today
        if home not in teams_playing_today and away not in teams_playing_today:
            todays_games.append((home, away))
            teams_playing_today.add(home)
            teams_playing_today.add(away)
        else:
            # Conflict: One of these teams plays today already. 
            # Push to next queue.
            next_queue.append((home, away))
    
    # Update the main queue to be the remaining games
    game_queue = next_queue
    
    # --- Generate SQL for Today's Games ---
    if todays_games:
        day_of_week = current_date.strftime("%A")
        month = current_date.strftime("%B")
        day_num = (current_date - start_date).days + 1
        week_num = int((current_date - start_date).days / 7) + 1
        
        for home, away in todays_games:
            val_str = f"(1, {week_num}, {day_num}, '{day_of_week}', '{month}', {current_date.day}, {current_date.year}, {home}, {away})"
            sql_lines.append(f"INSERT INTO quick_start_schedule (scenario_id, week_number, day_number, day_of_week, month_name, day_of_month, year, home_qs_team_id, away_qs_team_id) VALUES {val_str};")
            
    # --- Advance Date ---
    # "Day On, Day Off" cadence.
    # We increment by 2 days. 
    # (Exception: If we are near the end and have very few games left, we might just fill days)
    if len(game_queue) < 50:
        current_date += datetime.timedelta(days=1) # Speed up end of season
    else:
        current_date += datetime.timedelta(days=2) # Standard cadence

# ---------------------------------------------------------
# 4. WRITE TO FILE
# ---------------------------------------------------------
output_file = 'populate_schedule.sql'
with open(output_file, 'w') as f:
    f.write("\n".join(sql_lines))

print(f"Success! Balanced schedule created at: {output_file}")
print(f"Total Games Scheduled: {1230 - len(game_queue)}")
if len(game_queue) > 0:
    print(f"Warning: {len(game_queue)} games could not be scheduled within date limit.")