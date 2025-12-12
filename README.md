# Basketball 2026 - NBA Simulation Game

A comprehensive basketball league simulation web application built with Flask and PostgreSQL.

## Features

- **League Management**: Create and manage custom basketball leagues
- **Real-time Simulation**: Simulate games, days, or entire weeks
- **Team Management**: Control depth charts, coaching strategies, and rotations
- **Trading System**: Trade players and draft picks with AI-driven valuations
- **Free Agency**: Negotiate contracts with free agents
- **Playoff System**: Full playoff bracket with best-of-7 series
- **Statistics Tracking**: Detailed player and team statistics
- **Financial Management**: Salary cap management and contract extensions
- **Historical Records**: Track champions and season history

## Tech Stack

- **Backend**: Python 3.11, Flask
- **Database**: PostgreSQL (Neon)
- **Frontend**: HTML, CSS, JavaScript
- **Deployment**: Render

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL (or Neon account)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/basketball2026.git
   cd basketball2026
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   - Copy `.env.example` to `.env` (or create `.env`)
   - Add your database credentials:
     ```
     DB_NAME=your_database
     DB_USER=your_user
     DB_PASSWORD=your_password
     DB_HOST=your_host
     SECRET_KEY=your_secret_key
     ```

5. Initialize database:
   ```bash
   python import_to_neon.py
   ```

6. Run the application:
   ```bash
   python app.py
   ```

7. Open browser to `http://localhost:5000`

## Deployment

See [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) for detailed deployment instructions.

## Project Structure

```
basketball2026/
├── app.py                  # Main Flask application
├── simulation.py           # Game simulation engine
├── archive_season.py       # Season archiving utility
├── templates/              # HTML templates
├── static/                 # Static assets (CSS, images)
├── requirements.txt        # Python dependencies
└── .env                    # Environment variables (not in git)
```

## Game Mechanics

- **82-game season** with realistic scheduling
- **AI-driven trades** based on team performance and needs
- **Dynamic player ratings** across multiple attributes
- **Coaching strategies** affecting gameplay (pace, defense, rotations)
- **Realistic simulation** with fouls, assists, rebounds, turnovers
- **Playoff seeding** and best-of-7 series

## License

MIT License - feel free to use and modify!

## Support

For issues or questions, please open an issue on GitHub.
