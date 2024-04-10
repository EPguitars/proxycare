from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from scheduler.postgres_connector import DatabaseConnector, dbcredentials

unblocking_proxy_subprocess = BackgroundScheduler()

def call_update_blocked_function():
    with DatabaseConnector(**dbcredentials) as db:
        db.execute_update_query("SELECT update_blocked_status();")


unblocking_proxy_subprocess.add_job(call_update_blocked_function, trigger=IntervalTrigger(minutes=5))
