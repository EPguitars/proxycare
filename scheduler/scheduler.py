import json
import time

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_SERIALIZABLE
import redis
from scheduler.postgres_connector import DatabaseConnector, dbcredentials
#from postgres_connector import DatabaseConnector, dbcredentials

# decorator for limiting recursion calls
def limit_recursion(max_depth):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if wrapper.depth == max_depth:
                raise RecursionError("Max recursion depth reached.")
            wrapper.depth += 1
            result = func(*args, **kwargs)
            wrapper.depth -= 1
            return result
        wrapper.depth = 0
        return wrapper
    return decorator


class Scheduler:
    _instance = None
    _rate_limit = 5

    def __new__(cls, *args, **kwargs):
        """ Permorming Singleton """
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            # Initialize async Redis connection
            cls._instance._redis = None  # Will be initialized on first call
        return cls._instance

    def _get_redis(self):
        """ Initialize Redis connection """
        if not self._redis:
            self._redis = redis.Redis(host='localhost', port=6379, db=0)
        return self._redis

    @limit_recursion(10)
    def get_proxy(self, source_id):
        """ Get a proxy address from Redis """
        redis = self._get_redis()
        # Retrieve and delete the first proxy address from Redis
        proxy = redis.zpopmax(source_id)

        if not proxy:
            # If we operating second recursion 
            # it means that redis is empty
            # if redis is empty we need to wait for some time
            # for new proxies to be added to redis
            if self.get_proxy.depth > 1:
                time.sleep(self._rate_limit)

            self.send_batch_to_redis(source_id)
            return self.get_proxy(source_id)
        
        return proxy

    def get_proxies_from_db(self, source_id):
        extract_query = f"""SELECT * FROM proxies 
        WHERE blocked = False 
        AND sourceId = {source_id}
        LIMIT 100"""
        # ORDER BY priority DESC
        
        update_query = f"""UPDATE proxies
        SET blocked = True
        WHERE id in (
            SELECT id FROM proxies 
            WHERE blocked = False 
            AND sourceId = {source_id}
            LIMIT 100
        )"""

        with DatabaseConnector(**dbcredentials) as conn:
            try:
                # Transaction setup
                conn.connection.set_isolation_level(ISOLATION_LEVEL_SERIALIZABLE)
                cursor = conn.connection.cursor()
                # Get the column names from the table
                cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = 'proxies'")
                columns = [row[0] for row in cursor.fetchall()]

                # Fetch data from the table
                data = []
                rows = conn.execute_select_query(extract_query)
                for row in rows:
                    data.append({columns[i]: value for i, value in enumerate(row)})
                # Block the fetched proxies
                conn.execute_update_query(update_query)

                return data
            
            except psycopg2.Error as e:
                print("Error:", e)
                conn.connection.rollback()
                return []
    
    def send_batch_to_redis(self, source_id):
        # grab batch of proxies from db
        # store in redis
        redis = self._get_redis()

        db_proxies = self.get_proxies_from_db(source_id)
        for proxy in db_proxies:
            self.push_proxy_to_redis(source_id, proxy)

        redis.expire(source_id, 360)


    def push_proxy_to_redis(self, source_id, proxy_data):
        redis = self._get_redis()
        # Store the proxy address in Redis
        priority = proxy_data['priority']
        dumped_data = json.dumps(proxy_data)
        redis.zadd(source_id, {dumped_data: priority})