from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse


class SendMessageMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, request: Request, call_next):
        response = await call_next(request)
        # Check if the response status code is 200
        if response.status_code == 200:
            # Execute the logic for sending the message
            print("Message sent successfully")

        return response