import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Get database connection parameters from environment variables
dbcredentials = {
    "dbname": os.getenv("dbname", "ProxyManager"),
    "user": os.getenv("user", "postgres"),
    "password": os.getenv("password", "holocron2"),
    "host": os.getenv("host", "postgres"),  # Use 'postgres' as default in Docker
    "port": os.getenv("port", "5432")
}

class DatabaseConnector:
    def __init__(self, dbname, user, password, host, port):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.connection = None

    def connect(self):
        self.connection = psycopg2.connect(
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port
        )

    def close(self):
        if self.connection:
            self.connection.close()

    def execute_update_query(self, query):
        if not self.connection:
            raise RuntimeError("Database connection is not established.")
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            self.connection.commit()
    
    def execute_select_query(self, query):
        if not self.connection:
            raise RuntimeError("Database connection is not established.")
        with self.connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        return rows

    # Implementing the context manager protocol
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

