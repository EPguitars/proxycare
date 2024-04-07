import copy

from fastapi import (FastAPI, status, 
                     Depends, Request)
from fastapi.routing import APIRoute
from starlette.concurrency import iterate_in_threadpool
import uvicorn

from auth import verify_access
from scheduler.scheduler import Scheduler
from middlewares import SendMessageMiddleware

app = FastAPI()


@app.get("/get_proxy", status_code=status.HTTP_200_OK)
async def get_proxy(source_id: int, password: str = Depends(verify_access)):
    # request scheduler to get proxy for source
    scheduler = Scheduler()
    
    return scheduler.get_proxy(source_id)[0][0]


@app.middleware("http")
async def add_custom_header(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Custom-Header'] = 'My custom value'

    if "/get_proxy" == request.url.path and response.status_code == 200:
        # print the body of response
        response_body = [chunk async for chunk in response.body_iterator][0].decode()
        response.body_iterator = iterate_in_threadpool(iter(response_body))
        print("Message sent successfully")
    
    print("Custom header added")
    return response


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
