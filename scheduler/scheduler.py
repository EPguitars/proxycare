import json

import redis
from scheduler.postgres_connector import DatabaseConnector, dbcredentials
#from postgres_connector import DatabaseConnector, dbcredentials

class Scheduler:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            # Initialize async Redis connection
            cls._instance._redis = None  # Will be initialized on first call
        return cls._instance

    def _get_redis(self):
        if not self._redis:
            self._redis = redis.Redis(host='localhost', port=6379, db=0)
        return self._redis

    def get_proxy(self, source_id):
        redis = self._get_redis()
        # Retrieve and delete the first proxy address from Redis
        #proxy = redis.lpop(source_id)
        proxy = redis.zpopmax(source_id)
        print("proxy:", proxy)
        if not proxy:
            self.send_batch_to_redis(source_id)
            return self.get_proxy(source_id)
        
        return proxy

    def get_proxies_from_db(self, source_id):
        query = f"""SELECT * FROM proxies 
        WHERE blocked = False 
        AND sourceId = {source_id}
        LIMIT 100"""
        # ORDER BY priority DESC
        with DatabaseConnector(**dbcredentials) as conn:
            cursor = conn.connection.cursor()
            cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = 'proxies'")
            columns = [row[0] for row in cursor.fetchall()]

            # Fetch data from the table
            data = []
            rows = conn.execute_query(query)
            for row in rows:
                data.append({columns[i]: value for i, value in enumerate(row)})

            return data
        
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
        print(type(priority))
        dumped_data = json.dumps(proxy_data)
        #redis.rpush(source_id, dumped_data)
        redis.zadd(source_id, {dumped_data: priority})