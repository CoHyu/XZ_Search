import sqlite3
import os

def init_database():
    db_path = 'articles.db'
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        author TEXT,
        url TEXT UNIQUE NOT NULL,
        category TEXT,
        content_html TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON articles(title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_author ON articles(author)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON articles(category)')
    
    conn.commit()
    conn.close()
    
    print(f"database created at: {os.path.abspath(db_path)}")

if __name__ == '__main__':
    init_database()
