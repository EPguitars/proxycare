import subprocess
import json
from fastapi import (FastAPI, status, 
                     Depends, Request)
from starlette.concurrency import iterate_in_threadpool
import uvicorn

from api.auth import verify_access
from scheduler.scheduler import Scheduler
from scheduler.celery_worker import unblock_proxy
from scheduler.unblock_all_proxies import unblocking_proxy_subprocess

app = FastAPI()


@app.get("/get_proxy", status_code=status.HTTP_200_OK)
async def get_proxy(source_id: int, password: str = Depends(verify_access)):
    # request scheduler to get proxy for source
    scheduler = Scheduler()
    
    return scheduler.get_proxy(source_id)[0][0]


@app.middleware("http")
async def add_custom_header(request: Request, call_next):
    response = await call_next(request)

    if "/get_proxy" == request.url.path and response.status_code == 200:
        # print the body of response
        response_body = [chunk async for chunk in response.body_iterator][0].decode()
        unblock_proxy.apply_async(args=[json.loads(response_body)])
        response.body_iterator = iterate_in_threadpool(iter(response_body))
        
    return response


if __name__ == "__main__":
    # start redis sudo service redis-server start
    unblocking_proxy_subprocess.start()
    uvicorn.run(app, host="127.0.0.1", port=8000)
