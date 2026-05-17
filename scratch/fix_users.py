import sqlite3
import os

db_path = r'x:\Yuki Backend\db\creds.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET username = 'Sehaj_V2' WHERE id = 2")
    conn.commit()
    print(f"Renamed user ID 2 to Sehaj_V2. Rows affected: {cursor.rowcount}")
    
    cursor.execute("SELECT id, username, email FROM users")
    users = cursor.fetchall()
    print("\nFinal User List:")
    for u in users:
        print(f"ID: {u[0]} | Username: {u[1]} | Email: {u[2]}")
    conn.close()
else:
    print("DB not found")
