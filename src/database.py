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
                    email_password TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    used BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute("PRAGMA table_info(accounts)")
            columns = {info[1] for info in cursor.fetchall()}
            
            if 'password' in columns:
                pass

            if 'used' not in columns:
                try:
                    cursor.execute("ALTER TABLE accounts ADD COLUMN used BOOLEAN DEFAULT 0")
                except Exception as e:
                    print(f"Migration error (adding used column): {e}")

            conn.commit()

    def save_account(self, email, email_password, first_name, last_name, used=False):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO accounts (email, email_password, first_name, last_name, used)
                    VALUES (?, ?, ?, ?, ?)
                ''', (email, email_password, first_name, last_name, used))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            print(f"Database error: {e}")
            return False

    def get_all_accounts(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts')
            return [dict(row) for row in cursor.fetchall()]

    def get_account(self, email):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts WHERE email = ?', (email,))
            row = cursor.fetchone()
            return dict(row) if row else None
            
    def mark_account_used(self, email):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE accounts SET used = 1 WHERE email = ?', (email,))
                conn.commit()
            return True
        except Exception as e:
            print(f"Database error marking used: {e}")
            return False

