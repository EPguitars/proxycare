import uvicorn
from fastapi import FastAPI
from app.endpoints.routes import router
from app.core.config import settings
from app.utils.init_db import init_db
from app.cache.redis_cache import RedisCache
from app.endpoints.ws_proxy import initialize_proxy_pools

app = FastAPI(
    title="API Service",
    description="A small API service with authentication",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    # Initialize the admin user on startup
    init_db()
    
    # Initialize Redis cache and load proxies
    cache = RedisCache()
    cache.load_all_proxies()
    
    # Initialize proxy pools
    initialize_proxy_pools()

app.include_router(router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 