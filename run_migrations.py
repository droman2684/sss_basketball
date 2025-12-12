#!/usr/bin/env python3
"""
Run database migrations before starting the app.
This ensures the database schema is up to date.
"""
from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

def run_migrations():
    """Run all pending migrations"""
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            host=os.getenv('DB_HOST'),
            sslmode='require'
        )
        cur = conn.cursor()

        print("Running migrations...")

        # Migration 1: Add simulation_mode column
        try:
            cur.execute("""
                ALTER TABLE leagues
                ADD COLUMN IF NOT EXISTS simulation_mode VARCHAR(20) DEFAULT 'detailed'
            """)
            print("  ✓ Added simulation_mode column")
        except Exception as e:
            print(f"  - simulation_mode: {e}")

        # Migration 2: Add salary_cap column
        try:
            cur.execute("""
                ALTER TABLE leagues
                ADD COLUMN IF NOT EXISTS salary_cap BIGINT DEFAULT 140000000
            """)
            print("  ✓ Added salary_cap column")
        except Exception as e:
            print(f"  - salary_cap: {e}")

        conn.commit()
        cur.close()
        conn.close()

        print("Migrations complete!")
        return True

    except Exception as e:
        print(f"Migration error: {e}")
        return False

if __name__ == '__main__':
    run_migrations()
