import asyncio
import json 
import os
from collections import deque, defaultdict
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from starlette.websockets import WebSocketState
from loguru import logger

from app.core.database import SessionLocal
from app.models.models import Proxy, Statistic
from app.cache.redis_cache import RedisCache
from app.core.config import settings
from app.utils.crypto import encrypt_proxy
# Create a router for WebSocket endpoints
router = APIRouter()

# Global proxy pools by source_id
proxy_pools: Dict[str, deque] = {}
CACHE_FALLBACK_SOURCE = "1"

async def check_websocket_token(token = Query(...)):
    """
    Dependency to validate the token for WebSocket connections.
    Returns the WebSocket object if authenticated.
    """
    # Здесь твоя логика проверки токена
    print("Checking token")
    print(token)
    our_token = os.environ.get("SECRET")
    if token != our_token:
        # Можно бросить исключение или вернуть None
        raise Exception("Invalid token")
    return token

# Connection manager for websocket clients
class ConnectionManager:
    """
    Manages active WebSocket connections.
    """
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)

    async def accept_and_connect(self, websocket: WebSocket, key: str):
        """Accept the WebSocket connection and add it to active connections"""
        await websocket.accept()
        self.connect(websocket, key)

    def connect(self, websocket: WebSocket, key: str):
        """Add a connected WebSocket to the active connections for a key"""
        self.active_connections[key].append(websocket)
        logger.info(f"Client connected to {key}. Total connections: {len(self.active_connections[key])}")

    def disconnect(self, websocket: WebSocket, key: str):
        """Remove a disconnected WebSocket"""
        conns = self.active_connections.get(key, [])
        if websocket in conns:
            conns.remove(websocket)
            logger.info(f"Client disconnected from {key}. Remaining: {len(conns)}")
            
            # Clean up empty lists
            if not conns:
                del self.active_connections[key]

    async def send_json(self, websocket: WebSocket, message: dict):
        """Send a JSON message to a WebSocket"""
        try:
            # Check if the WebSocket is still connected before sending
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
        except WebSocketDisconnect:
            # Clean up if client disconnects
            self.disconnect(websocket, message.get("key", ""))
        except Exception as e:
            # Log the error but don't propagate it
            logger.error(f"Error sending message: {e}")

    async def broadcast(self, message: dict, key: str):
        """Broadcast a message to all connected clients for a specific key"""
        for connection in self.active_connections.get(key, []):
            await self.send_json(connection, message)

# Create a manager instance
manager = ConnectionManager()

def initialize_proxy_pools():
    """
    Populate in-memory pools from Redis on startup.
    """
    cache = RedisCache()
    all_proxies = cache.get_all_proxies() or []
    temp: Dict[str, List[dict]] = defaultdict(list)

    for proxy in all_proxies:
        src = str(proxy.get("sourceId"))
        temp[src].append(proxy)

    for src, plist in temp.items():
        proxy_pools[src] = deque(plist)
    
    logger.info(f"Initialized proxy pools with {len(proxy_pools)} sources")

async def save_proxy_report(proxy_id: int, status_code: int) -> tuple[bool, str]:
    """Persist a proxy report to DB and return success and error message."""
    try:
        db = SessionLocal()
        try:
            # First check if the proxy exists
            proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
            if not proxy:
                return False, f"Proxy with ID {proxy_id} does not exist"
            
            # Create the report
            report = Statistic(proxyid=proxy_id, statusid=status_code)
            db.add(report)
            db.commit()
            return True, ""
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error saving proxy report: {e}")
        return False, str(e)

async def handle_incoming(ws: WebSocket, key: str) -> bool:
    """
    Process inbound messages for report or control actions.
    Returns False if the WebSocket is closed, True otherwise.
    """
    # First check if the WebSocket is still connected
    if ws.client_state != WebSocketState.CONNECTED:
        return False
    
    try:
        msg = await asyncio.wait_for(ws.receive_json(), timeout=0.1)
        action = msg.get("action")
        
        if action == "report_proxy":
            pid = msg.get("proxy_id")
            code = msg.get("status_code")
            success, error_msg = await save_proxy_report(pid, code)
            
            # Check if the WebSocket is still open before sending
            if ws.client_state == WebSocketState.CONNECTED:
                await manager.send_json(ws, {
                    "action": "report_acknowledged", 
                    "proxy_id": pid, 
                    "success": success,
                    "message": error_msg if not success else "Report saved successfully"
                })
                
        elif action == "proxy_taken":
            # A client has taken a proxy - broadcast to other clients
            proxy_id = msg.get("proxy_id")
            usage_interval = msg.get("usage_interval", 30)
            
            # Broadcast to all clients for this source except the sender
            # First determine which source this proxy belongs to
            proxy_source = None
            for src, pool in proxy_pools.items():
                for proxy in pool:
                    if proxy.get('id') == proxy_id:
                        proxy_source = src
                        break
                if proxy_source:
                    break
            
            if proxy_source:
                # Broadcast to all clients connected to this source
                for connection in manager.active_connections.get(proxy_source, []):
                    if connection != ws:  # Don't send back to the client that took the proxy
                        await manager.send_json(connection, {
                            "action": "proxy_in_use",
                            "proxy_id": proxy_id,
                            "usage_interval": usage_interval,
                            "key": proxy_source
                        })
                
                # Also broadcast to clients connected to multiple sources that include this one
                for multi_key, connections in manager.active_connections.items():
                    if "," in multi_key and proxy_source in multi_key.split(","):
                        for connection in connections:
                            if connection != ws:
                                await manager.send_json(connection, {
                                    "action": "proxy_in_use",
                                    "proxy_id": proxy_id,
                                    "usage_interval": usage_interval,
                                    "key": multi_key
                                })
        
        # extend for other inbound actions
        return True
    except asyncio.TimeoutError:
        # no message, continue
        return True
    except WebSocketDisconnect:
        return False
    except Exception as e:
        logger.error(f"Error handling incoming message: {e}")
        # Only try to notify client if the connection is still open
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await manager.send_json(ws, {"action": "error", "message": f"Error processing message: {str(e)}"})
            except Exception:
                # Ignore errors when trying to send error messages
                pass
        return ws.client_state == WebSocketState.CONNECTED

async def multi_source_proxy_provider(
    websocket: WebSocket,
    source_ids: List[str],
    already_accepted: bool = True
):
    """
    Provides proxies from multiple sources in round-robin fashion over a single WS.
    Handles incoming report messages on the same connection.
    Uses each proxy's individual usage_interval for blocking.
    """
    key = ",".join(source_ids)
    
    # Use the appropriate connection method based on whether the WebSocket is already accepted
    if already_accepted:
        manager.connect(websocket, key)
    else:
        await manager.accept_and_connect(websocket, key)
    
    try:
        idx = 0
        while True:
            # Check if the WebSocket is still connected
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.info(f"WebSocket disconnected, exiting provider loop for {key}")
                break
                
            # Process any reports, exit loop if WebSocket is closed
            if not await handle_incoming(websocket, key):
                logger.info(f"WebSocket closed during message handling for {key}")
                break

            # Then dispatch next proxy
            try:
                for sid in source_ids:
                    pool = proxy_pools.get(sid)
                    if pool and pool:
                        proxy = pool.popleft()
                        
                        # Check connection again before sending
                        if websocket.client_state != WebSocketState.CONNECTED:
                            # Put the proxy back and exit
                            pool.appendleft(proxy)
                            return
                        
                        # Get the proxy's individual usage_interval (default to 30 if not set)
                        usage_interval = proxy.get('usage_interval', 30)
                        secret = os.environ.get("SECRET", "")
                        encrypted_proxy = encrypt_proxy(proxy, secret)
                        
                        await manager.send_json(websocket, {
                            "action": "proxy_available", 
                            "source_id": sid, 
                            "proxy": encrypted_proxy, 
                            "key": key,
                            "usage_interval": usage_interval  # Include the interval in the response
                        })
                        
                        # Schedule return based on the proxy's individual usage_interval
                        asyncio.get_event_loop().call_later(
                            usage_interval,
                            lambda p=proxy, s=sid: proxy_pools[s].append(p)
                        )
                        break
                else:
                    # No proxies available in any source
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await manager.send_json(websocket, {"action": "waiting", "message": "No proxies available, waiting...", "key": key})
                    await asyncio.sleep(1)
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during proxy dispatch for {key}")
                break
            except Exception as e:
                logger.error(f"Error dispatching proxy: {e}")
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {key}")
    
    except Exception as e:
        logger.error(f"Error in multi_source_proxy_provider: {e}")
        try:
            # Only try to send an error if the WebSocket is still connected
            if websocket.client_state == WebSocketState.CONNECTED:
                await manager.send_json(websocket, {"action": "error", "message": f"Server error: {e}", "key": key})
                await websocket.close(code=1011)
        except Exception:
            # Ignore errors when trying to send error messages
            pass
    
    finally:
        # Always disconnect from the manager
        manager.disconnect(websocket, key)
        logger.info(f"Cleaned up connection for {key}")

async def proxy_producer(websocket: WebSocket, source_id: str, already_accepted: bool = True):
    """
    Continuously send proxies from a single source pool to client.
    Handles incoming report messages on the same connection.
    Uses each proxy's individual usage_interval for blocking.
    """
    key = source_id
    
    # Use the appropriate connection method based on whether the WebSocket is already accepted
    if already_accepted:
        manager.connect(websocket, key)
    else:
        await manager.accept_and_connect(websocket, key)
    
    try:
        while True:
            # Check if the WebSocket is still connected
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.info(f"WebSocket disconnected, exiting producer loop for {key}")
                break
                
            # Process any reports, exit loop if WebSocket is closed
            if not await handle_incoming(websocket, key):
                logger.info(f"WebSocket closed during message handling for {key}")
                break

            try:
                pool = proxy_pools.get(source_id)
                if pool:
                    proxy = pool.popleft()
                    
                    # Check connection again before sending
                    if websocket.client_state != WebSocketState.CONNECTED:
                        # Put the proxy back and exit
                        pool.appendleft(proxy)
                        return
                    
                    # Get the proxy's individual usage_interval (default to 30 if not set)
                    usage_interval = proxy.get('usage_interval', 30)
                    
                    await manager.send_json(websocket, {
                        "action": "proxy_available", 
                        "proxy": proxy, 
                        "key": key,
                        "usage_interval": usage_interval  # Include the interval in the response
                    })
                    
                    # Schedule return based on the proxy's individual usage_interval
                    asyncio.get_event_loop().call_later(
                        usage_interval,
                        lambda p=proxy: proxy_pools[source_id].append(p)
                    )
                else:
                    # No proxies available
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await manager.send_json(websocket, {"action": "waiting", "message": "No proxies available, waiting...", "key": key})
                    await asyncio.sleep(1)
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during proxy dispatch for {key}")
                break
            except Exception as e:
                logger.error(f"Error dispatching proxy: {e}")
                if websocket.client_state != WebSocketState.CONNECTED:
                    break
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {key}")
    
    except Exception as e:
        logger.error(f"Error in proxy_producer: {e}")
        try:
            # Only try to send an error if the WebSocket is still connected
            if websocket.client_state == WebSocketState.CONNECTED:
                await manager.send_json(websocket, {"action": "error", "message": f"Server error: {e}", "key": key})
                await websocket.close(code=1011)
        except Exception:
            # Ignore errors when trying to send error messages
            pass
    
    finally:
        # Always disconnect from the manager
        manager.disconnect(websocket, key)
        logger.info(f"Cleaned up connection for {key}")

async def load_proxies_for_sources(source_ids: list) -> list:
    """Load or refresh proxies for specific sources into the cache"""
    cache = RedisCache()
    db = SessionLocal()
    loaded_sources = []
    
    try:
        for source_id in source_ids:
            # Query proxies for this source from the database
            proxies = db.query(Proxy).filter(Proxy.sourceid == source_id).all()
            
            if not proxies:
                continue
            
            # Create a pipeline for batch operations
            pipe = cache.redis.pipeline()
            
            # Clear existing proxies for this source
            pipe.delete(f"proxies:source:{source_id}")
            
            # Store each proxy in the cache
            proxy_count = 0
            for proxy in proxies:
                proxy_data = {
                    "id": proxy.id,
                    "proxy": proxy.proxy,
                    "sourceId": proxy.sourceid,
                    "source": proxy.source.source if proxy.source else None,
                    "priority": proxy.priority,
                    "blocked": proxy.blocked,
                    "provider": proxy.provider,
                    "provider_name": proxy.provider_relation.provider if proxy.provider_relation else None,
                    "updatedAt": proxy.updatedat.isoformat() if proxy.updatedat else None,
                    "usage_interval": proxy.usage_interval
                }
                
                # Add to source-specific list
                pipe.rpush(f"proxies:source:{source_id}", json.dumps(proxy_data))
                
                # Also store by ID for quick lookups
                pipe.set(f"proxy:{proxy.id}", json.dumps(proxy_data))
                
                proxy_count += 1
            
            # Execute all commands in the pipeline
            pipe.execute()
            
            # If we loaded proxies, add this source to the result
            if proxy_count > 0:
                # Also update the proxy pool for this source
                if source_id not in proxy_pools:
                    proxy_pools[source_id] = deque()
                else:
                    proxy_pools[source_id].clear()
                
                # Get the cached proxies and add to pool
                cached_proxies = cache.get_proxies_by_source(source_id)
                for proxy in cached_proxies:
                    proxy_pools[source_id].append(proxy)
                
                loaded_sources.append({
                    "source_id": source_id,
                    "proxy_count": proxy_count
                })
        
        return loaded_sources
    
    finally:
        db.close()


@router.websocket("/ws/proxy_multi")
async def websocket_proxy_multi(
    websocket: WebSocket):
    """
    WS endpoint for multi-source proxy delivery and reporting.
    Expects a JSON message {"action":"start","source_ids":[...]}
    Requires authentication token in query param or headers.
    """
    try:
        await websocket.accept()
        
        msg = await websocket.receive_json()
        if msg.get("action") != "start" or not isinstance(msg.get("source_ids"), list):
            await websocket.send_json({"action": "error", "message": "Invalid start message"})
            await websocket.close(code=1008)
            return
        
        # Pass already_accepted=True since we accepted the connection above
        await multi_source_proxy_provider(websocket, msg["source_ids"], already_accepted=True)
    except HTTPException as e:
        # Handle authentication errors
        await websocket.accept()
        await websocket.send_json({"action": "error", "message": e.detail})
        await websocket.close(code=1008)
    except Exception as e:
        logger.error(f"Error in websocket_proxy_multi: {e}")

@router.websocket("/ws/proxies")
async def websocket_proxies(websocket: WebSocket):
    """
    WebSocket endpoint for multiple source proxy access.
    Requires authentication token in query param or headers.
    """
    try:
        await websocket.accept()
        
        # Receive initial configuration message with source_ids
        init_message = await websocket.receive_json()
        source_ids = init_message.get('source_ids', [])
        
        if not source_ids:
            await websocket.send_json({
                "action": "error",
                "message": "No source_ids provided. Please specify at least one source_id."
            })
            await websocket.close(code=1008)
            return
        
        # Convert all source_ids to strings for consistency
        source_ids = [str(source_id) for source_id in source_ids]
        
        # Load/refresh proxies for the requested sources
        loaded_sources = await load_proxies_for_sources(source_ids)
        
        # Inform client about loaded sources
        await websocket.send_json({
            "action": "sources_loaded",
            "loaded_sources": loaded_sources,
            "message": f"Loaded proxies from {len(loaded_sources)} sources"
        })
        
        # Start proxy provider for all requested sources
        await multi_source_proxy_provider(websocket, source_ids, already_accepted=True)
    
    except HTTPException as e:
        # Handle authentication errors
        await websocket.accept()
        await websocket.send_json({"action": "error", "message": e.detail})
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        logger.info(f"Client disconnected")
    except Exception as e:
        logger.error(f"Error in WebSocket connection: {str(e)}")
        if websocket.client_state != WebSocketState.CONNECTED:
            await websocket.close(code=1011, reason=f"Error: {str(e)}")
