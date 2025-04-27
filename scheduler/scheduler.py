import json
import time
import logging
import os
from dotenv import load_dotenv
from datetime import datetime

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ
import redis
from scheduler.postgres_connector import DatabaseConnector, dbcredentials

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

# Add this class at the top of your file
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DateTimeEncoder, self).default(obj)

class Scheduler:
    _instance = None
    _rate_limit = 5

    def __new__(cls, *args, **kwargs):
        """ Performing Singleton """
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            # Initialize async Redis connection
            cls._instance._redis = None  # Will be initialized on first call
        return cls._instance

    def _get_redis(self):
        """ Initialize Redis connection """
        if not self._redis:
            load_dotenv()
            redis_url = os.getenv('CELERY_BROKER_URL')

            # Parse the Redis URL to get connection parameters
            # If using redis://redis:6379/0 format
            if redis_url and redis_url.startswith('redis://'):
                # Extract host, port, db from URL
                parts = redis_url.replace('redis://', '').split(':')
                host = parts[0]
                port_db = parts[1].split('/')
                port = int(port_db[0])
                db = int(port_db[1]) if len(port_db) > 1 else 0
                
                self._redis = redis.Redis(host=host, port=port, db=db)
            else:
                # Fallback to default
                self._redis = redis.Redis(host='redis', port=6379, db=0)
        return self._redis

    @limit_recursion(10)
    def get_proxy(self, source_id):
        """ Get a proxy address from Redis """
        redis = self._get_redis()
        # Retrieve and delete the first proxy address from Redis
        proxy = redis.zpopmax(source_id)
        print("1111111111111111111")
        print(proxy)
        if not proxy:
            # If Redis is empty, try to send a batch of proxies
            try:
                # Log that we're trying to refill Redis
                print(f"Redis empty for source_id {source_id}, attempting to refill...")
                
                # Try to send a batch to Redis
                batch_result = self.send_batch_to_redis(source_id)
                
                # Check if any proxies were actually added
                if not batch_result:
                    # If no proxies were added, return a default response
                    print(f"No proxies available for source_id {source_id}")
                    return [("No proxies available", 0)]
                
                # If we're in a deep recursion, add a small delay
                if hasattr(self.get_proxy, 'depth') and self.get_proxy.depth > 1:
                    time.sleep(self._rate_limit)
                
                # Try again with the newly added proxies
                return self.get_proxy(source_id)
            except Exception as e:
                # If there's an error, log it and return a default response
                print(f"Error refilling proxies: {str(e)}")
                return [("Error retrieving proxy", 0)]
        
        return proxy

    def get_proxies_from_db(self, source_id, proxies_amount):
        extract_query = f"""SELECT * FROM proxies 
        WHERE blocked = False 
        AND sourceId = {source_id}
        ORDER BY priority DESC
        LIMIT {proxies_amount}"""
        
        update_query = f"""UPDATE proxies
        SET blocked = True
        WHERE id in (
            SELECT id FROM proxies 
            WHERE blocked = False 
            AND sourceId = {source_id}
            ORDER BY priority DESC
            LIMIT {proxies_amount}
        )"""

        with DatabaseConnector(**dbcredentials) as conn:
            try:
                # Transaction setup
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
                logging.error("Error while fetching proxies from the database: {1}".format(e))
                conn.connection.rollback()
                return []
    
    def send_batch_to_redis(self, source_id, proxy_amount=10):
        """
        Send a batch of proxies to Redis
        
        Returns:
            bool: True if proxies were added, False otherwise
        """
        # grab batch of proxies from db
        # store in redis
        redis = self._get_redis()

        db_proxies = self.get_proxies_from_db(source_id, proxy_amount)
        for proxy in db_proxies:
            self.push_proxy_to_redis(source_id, proxy)

        redis.expire(source_id, 360)

        # Add a return value to indicate success
        return len(db_proxies) > 0  # Return True if proxies were added

    def push_proxy_to_redis(self, source_id, proxy_data):
        """ Function for adding fresh proxy to Redis """
        # Get connection to Redis
        redis = self._get_redis()
        
        # Store the proxy address in Redis
        priority = proxy_data['priority']
        
        # Create a copy of the proxy data to avoid modifying the original
        proxy_json = proxy_data.copy()
        
        # Remove updatedat field if it exists
        if "updatedat" in proxy_json:
            del proxy_json["updatedat"]
        
        # Dump json to string using the custom encoder
        dumped_data = json.dumps(proxy_json, cls=DateTimeEncoder)
        redis.zadd(source_id, {dumped_data: priority})

