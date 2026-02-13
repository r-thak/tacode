import sqlite3
import os
from datetime import datetime

class Database:
    def __init__(self, db_path="accounts.sqlite"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email_password TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Migration: add email_password if it doesn't exist
            cursor.execute("PRAGMA table_info(accounts)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'email_password' not in columns:
                cursor.execute("ALTER TABLE accounts ADD COLUMN email_password TEXT")
            
            conn.commit()

    def save_account(self, email, password, email_password, first_name, last_name):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO accounts (email, password, email_password, first_name, last_name)
                    VALUES (?, ?, ?, ?, ?)
                ''', (email, password, email_password, first_name, last_name))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            print(f"Database error: {e}")
            return False

    def get_all_accounts(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts')
            return cursor.fetchall()

    def get_account(self, email):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts WHERE email = ?', (email,))
            row = cursor.fetchone()
            return dict(row) if row else None
