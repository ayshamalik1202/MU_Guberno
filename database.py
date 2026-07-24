import mysql.connector
from config import Config

def get_db():
    return mysql.connector.connect(
        host     = Config.DB_HOST,
        user     = Config.DB_USER,
        password = Config.DB_PASSWORD,
        database = Config.DB_NAME
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