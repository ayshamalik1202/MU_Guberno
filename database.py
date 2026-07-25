import mysql.connector
from config import Config
import os

def get_db():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST', Config.DB_HOST),
        user=os.environ.get('DB_USER', Config.DB_USER),
        password=os.environ.get('DB_PASSWORD', Config.DB_PASSWORD),
        database=os.environ.get('DB_NAME', Config.DB_NAME)
    )
get_db_connection = get_db
def init_db(app=None):
    """
    Optional: Verifies the database connection on startup.
    """
    try:
        conn = get_db()
        print("Connected to MU_Guberno Database successfully!")
        conn.close()
    except Exception as err:
        print(f"Database Connection failed during initialization: {err}")