import asyncio
import json
from collections import deque, defaultdict
from typing import Dict, List, Optional
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db, SessionLocal
from app.core.security import authenticate_user, create_access_token, get_current_user, verify_api_key
from app.core.config import settings
from app.crud.crud import store_token
from app.schemas.schemas import TokenSchema, User, DataResponse
from app.cache.redis_cache import RedisCache
from app.models.models import Proxy, Source, Statistic
from loguru import logger

# Import WebSocket router and functions
from app.endpoints.ws_proxy import router as ws_router, proxy_pools, initialize_proxy_pools

router = APIRouter()

# Include the WebSocket router
router.include_router(ws_router)

# API endpoints
@router.post("/token", response_model=TokenSchema)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    # Store token in the database
    store_token(db, access_token, user.id)
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/health")
async def health_check():
    return {"status": "healthy"}

@router.get("/proxies/refresh")
async def refresh_proxy_pools():
    """Refresh proxy pools from Redis cache"""
    cache = RedisCache()
    cache.refresh_cache()
    initialize_proxy_pools()
    return {"message": "Proxy pools refreshed", "pools": len(proxy_pools)}

@router.post("/proxies/pools/{source_id}/add")
async def add_proxy_to_pool(source_id: str, proxy_data: dict):
    """Add a proxy to a specific pool"""
    if source_id not in proxy_pools:
        proxy_pools[source_id] = deque()
    
    proxy_pools[source_id].append(proxy_data)
    
    # Import manager from ws_proxy to broadcast messages
    from app.endpoints.ws_proxy import manager
    
    # Notify all connected clients for this source
    await manager.broadcast(
        {"action": "pool_updated", "count": len(proxy_pools[source_id])},
        source_id
    )
    
    return {"message": f"Proxy added to pool {source_id}", "pool_size": len(proxy_pools[source_id])}

@router.get("/debug/pools")
async def debug_pools():
    """Debug endpoint to check proxy pools"""
    return {
        "pools": {k: len(v) for k, v in proxy_pools.items()},
        "pool_keys": list(proxy_pools.keys()),
        "test_source": "1" in proxy_pools
    }

@router.get("/proxies/{proxy_id}/reports")
async def get_proxy_reports(proxy_id: int, db: Session = Depends(get_db)):
    """Get all reports for a specific proxy"""
    reports = db.query(Statistic).filter(Statistic.proxyid == proxy_id).all()
    
    if not reports:
        return {"proxy_id": proxy_id, "reports": []}
    
    return {
        "proxy_id": proxy_id,
        "reports": [
            {
                "id": report.id,
                "status_code": report.statusid,
                "reported_at": None  # Statistic doesn't have a timestamp field
            }
            for report in reports
        ]
    }

