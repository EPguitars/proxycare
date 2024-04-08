import os
import json
import time

from celery import Celery
from dotenv import load_dotenv

from scheduler.postgres_connector import DatabaseConnector, dbcredentials
from scheduler.scheduler import Scheduler

load_dotenv()

celery_broker = os.getenv("CELERY_BROKER_URL")
celery_backend = os.getenv("CELERY_RESULT_BACKEND")
RATE_LIMIT = int(os.getenv("RATE_LIMIT"))
celery_app = Celery('scheduler', broker=celery_broker)


@celery_app.task
def unblock_proxy(proxy_dumped):
    proxy = json.loads(proxy_dumped)
    proxy_id = str(proxy["id"])
    
    with DatabaseConnector(**dbcredentials) as db:
        scheduler = Scheduler()
        scheduler.send_batch_to_redis(proxy["sourceid"], proxy_amount=1)
        
        time.sleep(RATE_LIMIT)
        db.execute_update_query(f"UPDATE proxies SET blocked = false WHERE id = {proxy_id}")

        

    

    # Unblock the proxy in the database

registered_tasks = celery_app.tasks.keys()

# running worker celery -A scheduler.celery_worker worker -l info -c 50 -P eventlet