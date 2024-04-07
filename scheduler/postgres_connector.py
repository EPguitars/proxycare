import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()

dbcredentials = {
    "dbname": os.getenv("dbname"),
    "user": os.getenv("user"),
    "password": os.getenv("password"),
    "host": os.getenv("host"),
    "port": os.getenv("port"),
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

