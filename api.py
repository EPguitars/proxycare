import logging
import time
import threading

from fastapi import FastAPI, Query, HTTPException, status, Depends
from pydantic import BaseModel
import uvicorn
from rich import print

from manager import proxy_storage

app = FastAPI()


def verify_access(
    password: str = Query(..., description="The password for access"),
    shop: str = Query(..., description="shop"),
):
    correct_password = "zkW0HhlEcLrXGx0"  # Replace with your actual secure password
    if password != correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"password": password, "shop": shop}



@app.get("/get_proxy")
async def get_proxy(shop : dict = Depends(verify_access)):
    
    return proxy_storage[shop["shop"]].get_proxy()



if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)