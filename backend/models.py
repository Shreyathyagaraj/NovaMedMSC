import sqlite3

def init_db():
    conn = sqlite3.connect("patients.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            FirstName TEXT,
            LastName TEXT,
            PhoneNumber TEXT,
            patient_id TEXT UNIQUE
        )
    ''')
    conn.commit()
    conn.close()

def save_patient(first_name, last_name, phone_number, patient_id):
    conn = sqlite3.connect("patients.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO patients (first_name, last_name, phone_number, patient_id)
        VALUES (?, ?, ?, ?)
    ''', (first_name, last_name, phone_number, patient_id))
    conn.commit()
    conn.close()
