import logging
import time
import threading

from fastapi import FastAPI, Query, HTTPException, status
from pydantic import BaseModel
import uvicorn
from rich import print

from manager import proxy_storage

app = FastAPI()

class CustomReport(BaseModel):
    shop: str


@app.post("/get_proxy")
async def get_proxy(shop: CustomReport, password: str):
    correct_password = "5KW0sjYDYhMCevl"
    
    if password != correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return proxy_storage[shop.shop].get_proxy()



if __name__ == "__main__":
    
    uvicorn.run(app, host="127.0.0.1", port=8000)