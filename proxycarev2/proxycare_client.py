import asyncio
import json
import logging
from typing import List, Dict, Optional, Any
import websockets
from websockets.exceptions import ConnectionClosed
import time
import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class ProxyClient:
    """
    Async WebSocket client to receive real-time proxy updates and send reports.
    Automatically reconnects on connection loss.
    Tracks individual proxy usage intervals in real-time.
    """
    def __init__(self, base_url: str, source_ids: List[str], api_key: str, reconnect_delay: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.source_ids = source_ids
        self.api_key = api_key  # Store the API key for authentication
        self.reconnect_delay = reconnect_delay
        
        # Store proxies by source with tracking information
        self.proxies_by_source: Dict[str, List[Dict]] = {sid: [] for sid in source_ids}
        
        # Track which proxies are currently in use with their release time
        self.in_use_proxies: Dict[int, float] = {}
        
        # Track when proxies were last used to enforce minimum delay between reuse
        self.last_used_time: Dict[int, float] = {}
        self.reuse_delay = 1.0  # Minimum seconds between proxy reuse
        
        self._outgoing: asyncio.Queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._availability_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Determine WebSocket endpoint and optional start message
        if len(self.source_ids) == 1:
            sid = self.source_ids[0]
            self.ws_url = f"{self.base_url}/ws/proxy/{sid}?token={self.api_key}"
            self._start_message = None
        else:
            self.ws_url = f"{self.base_url}/ws/proxy_multi?token={self.api_key}"
            self._start_message = {"action": "start", "source_ids": self.source_ids}

    def start(self):
        """Start the background client tasks."""
        if not self._task:
            self._task = asyncio.create_task(self._run())
            self._availability_task = asyncio.create_task(self._update_proxy_availability())
            logger.info("Started ProxyClient background tasks")

    async def stop(self):
        """Signal to stop and await task completion."""
        self._stop_event.set()
        tasks = []
        if self._task:
            tasks.append(self._task)
        if self._availability_task:
            tasks.append(self._availability_task)
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Stopped ProxyClient background tasks")

    async def send_report(self, proxy_id: int, status_code: int):
        """Send a proxy report to the server."""
        msg = {"action": "report_proxy", "proxy_id": proxy_id, "status_code": status_code}
        await self._outgoing.put(msg)
        logger.info(f"Queued report for proxy {proxy_id} with status {status_code}")

    async def _update_proxy_availability(self):
        """Background task that periodically checks for proxies that should be released."""
        logger.info("Started proxy availability monitoring task")
        try:
            while not self._stop_event.is_set():
                await self._release_available_proxies()
                await asyncio.sleep(0.5)  # Check every half second
        except Exception as e:
            logger.error(f"Error in proxy availability monitoring: {e}")
        finally:
            logger.info("Stopped proxy availability monitoring task")
    
    async def _release_available_proxies(self):
        """Check for and release proxies that are no longer blocked."""
        current_time = time.time()
        released_ids = []
        
        async with self._lock:
            # Find proxies that have exceeded their block time
            for proxy_id, release_time in self.in_use_proxies.items():
                if current_time >= release_time:
                    released_ids.append(proxy_id)
            
            # Release each proxy
            for proxy_id in released_ids:
                # Remove from tracking dict
                del self.in_use_proxies[proxy_id]
                # Record the time this proxy was released
                self.last_used_time[proxy_id] = current_time
                
                # Find in source lists and update status
                for src, proxies in self.proxies_by_source.items():
                    for i, proxy in enumerate(proxies):
                        if proxy.get('id') == proxy_id and proxy.get('_in_use', False):
                            # Mark as available again
                            self.proxies_by_source[src][i]['_in_use'] = False
                            logger.info(f"Proxy {proxy_id} from source {src} is now AVAILABLE again")
                            break

    async def get_proxy(self, source_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a proxy with the highest priority from the specified source.
        If source_id is None, get from any available source.
        Enforces minimum delay between proxy reuse.
        """
        # First ensure any newly available proxies are released
        await self._release_available_proxies()
        
        current_time = time.time()
        
        async with self._lock:
            # If source_id is specified, get from that source
            if source_id:
                if source_id not in self.proxies_by_source:
                    logger.warning(f"Source ID {source_id} not found in available sources")
                    return None
                
                # Filter proxies that are available AND haven't been used too recently
                available_proxies = [
                    p for p in self.proxies_by_source[source_id] 
                    if not p.get('_in_use', False) and 
                    current_time - self.last_used_time.get(p.get('id'), 0) >= self.reuse_delay
                ]
                
                if not available_proxies:
                    recently_released = [
                        p for p in self.proxies_by_source[source_id]
                        if not p.get('_in_use', False) and p.get('id') in self.last_used_time
                    ]
                    
                    if recently_released:
                        # Some proxies are available but too recently used
                        oldest_proxy = min(recently_released, key=lambda p: current_time - self.last_used_time.get(p.get('id'), 0))
                        proxy_id = oldest_proxy.get('id')
                        wait_time = self.reuse_delay - (current_time - self.last_used_time.get(proxy_id, 0))
                        logger.warning(
                            f"Proxy {proxy_id} was just released {current_time - self.last_used_time.get(proxy_id, 0):.1f}s ago. "
                            f"Waiting {wait_time:.1f}s before reuse"
                        )
                    else:
                        logger.warning(f"No available proxies for source {source_id} - all are blocked")
                    
                    return None
                
                # Sort by priority (highest first) and return the top one
                available_proxies.sort(key=lambda p: p.get('priority', 0), reverse=True)
                proxy = available_proxies[0]
                
                # Mark this proxy as in use
                proxy_id = proxy.get('id')
                usage_interval = proxy.get('usage_interval', 30)
                self.in_use_proxies[proxy_id] = current_time + usage_interval
                
                # Mark in the source list too
                for i, p in enumerate(self.proxies_by_source[source_id]):
                    if p.get('id') == proxy_id:
                        self.proxies_by_source[source_id][i]['_in_use'] = True
                        break
                
                # Notify other clients this proxy is in use
                await self._outgoing.put({
                    "action": "proxy_taken", 
                    "proxy_id": proxy_id, 
                    "usage_interval": usage_interval
                })
                
                # Record the time when we started using this proxy
                time_since_last_use = current_time - self.last_used_time.get(proxy_id, 0)
                logger.info(
                    f"Retrieved proxy {proxy_id} from source {source_id}, BLOCKED for {usage_interval} seconds "
                    f"(last used {time_since_last_use:.1f}s ago)"
                )
                return proxy
            
            # If no source_id specified, find the source with highest priority proxy
            best_proxy = None
            best_source = None
            best_priority = -1
            
            for sid, proxies in self.proxies_by_source.items():
                # Filter proxies that are available AND haven't been used too recently
                available_proxies = [
                    p for p in proxies 
                    if not p.get('_in_use', False) and 
                    current_time - self.last_used_time.get(p.get('id'), 0) >= self.reuse_delay
                ]
                
                if not available_proxies:
                    continue
                
                # Find highest priority proxy in this source
                highest = max(available_proxies, key=lambda p: p.get('priority', 0), default=None)
                if highest and highest.get('priority', 0) > best_priority:
                    best_proxy = highest
                    best_source = sid
                    best_priority = highest.get('priority', 0)
            
            if best_proxy and best_source:
                # Mark this proxy as in use
                proxy_id = best_proxy.get('id')
                usage_interval = best_proxy.get('usage_interval', 30)
                self.in_use_proxies[proxy_id] = current_time + usage_interval
                
                # Mark in the source list too
                for i, p in enumerate(self.proxies_by_source[best_source]):
                    if p.get('id') == proxy_id:
                        self.proxies_by_source[best_source][i]['_in_use'] = True
                        break
                
                # Notify other clients this proxy is in use
                await self._outgoing.put({
                    "action": "proxy_taken", 
                    "proxy_id": proxy_id, 
                    "usage_interval": usage_interval
                })
                
                # Record the time when we started using this proxy
                time_since_last_use = current_time - self.last_used_time.get(proxy_id, 0)
                logger.info(
                    f"Retrieved proxy {proxy_id} from source {best_source}, BLOCKED for {usage_interval} seconds "
                    f"(last used {time_since_last_use:.1f}s ago)"
                )
                return best_proxy
            
            # Check if there are any recently released proxies
            recently_released = []
            for sid, proxies in self.proxies_by_source.items():
                for p in proxies:
                    proxy_id = p.get('id')
                    if not p.get('_in_use', False) and proxy_id in self.last_used_time:
                        recently_released.append((proxy_id, self.last_used_time[proxy_id], sid))
            
            if recently_released:
                # Some proxies are available but too recently used
                oldest_proxy_id, release_time, src = min(recently_released, key=lambda x: current_time - x[1])
                wait_time = self.reuse_delay - (current_time - release_time)
                logger.warning(
                    f"Proxy {oldest_proxy_id} from source {src} was just released {current_time - release_time:.1f}s ago. "
                    f"Waiting {wait_time:.1f}s before reuse"
                )
            else:
                logger.warning("No proxies available from any source - all are blocked")
            
            return None

    def get_proxy_status(self, proxy_id: int) -> Dict[str, Any]:
        """Get current status information for a specific proxy."""
        status = {
            "proxy_id": proxy_id,
            "in_use": False,
            "time_remaining": 0,
            "source": None,
            "last_used": 0
        }
        
        current_time = time.time()
        
        # Check if proxy is in use
        if proxy_id in self.in_use_proxies:
            release_time = self.in_use_proxies[proxy_id]
            time_remaining = max(0, release_time - current_time)
            status["in_use"] = True
            status["time_remaining"] = time_remaining
        
        # Check when it was last used
        if proxy_id in self.last_used_time:
            status["last_used"] = current_time - self.last_used_time[proxy_id]
        
        # Find which source this proxy belongs to
        for src, proxies in self.proxies_by_source.items():
            for proxy in proxies:
                if proxy.get('id') == proxy_id:
                    status["source"] = src
                    status["priority"] = proxy.get('priority', 0)
                    status["usage_interval"] = proxy.get('usage_interval', 30)
                    status["_in_use"] = proxy.get('_in_use', False)
                    break
            if status["source"]:
                break
        
        return status

    def get_all_proxies_status(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get status information for all proxies grouped by source."""
        result = {}
        current_time = time.time()
        
        for src, proxies in self.proxies_by_source.items():
            proxy_statuses = []
            for proxy in proxies:
                proxy_id = proxy.get('id')
                status = {
                    "id": proxy_id,
                    "in_use": proxy.get('_in_use', False),
                    "priority": proxy.get('priority', 0),
                    "time_remaining": 0,
                    "last_used": 0
                }
                
                if proxy_id in self.in_use_proxies:
                    release_time = self.in_use_proxies[proxy_id]
                    status["time_remaining"] = max(0, release_time - current_time)
                
                if proxy_id in self.last_used_time:
                    status["last_used"] = current_time - self.last_used_time[proxy_id]
                
                proxy_statuses.append(status)
            
            result[src] = proxy_statuses
        
        return result

    async def _run(self):
        """Main client loop."""
        logger.info(f"Starting ProxyCare client for sources: {self.source_ids}")
        while not self._stop_event.is_set():
            try:
                # Connect to WebSocket server
                logger.info(f"Connecting to {self.ws_url}...")
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("Connected to WebSocket server")
                    
                    # Send start message if needed
                    if self._start_message:
                        await ws.send(json.dumps(self._start_message))

                    # Create tasks
                    receiver = asyncio.create_task(self._receiver(ws))
                    sender = asyncio.create_task(self._sender(ws))
                    stopper = asyncio.create_task(self._stop_event.wait())

                    # Request initial proxies
                    await ws.send(json.dumps({"action": "request_proxy"}))

                    done, pending = await asyncio.wait(
                        {receiver, sender, stopper},
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                    # If stop_event triggered, break loop
                    if stopper in done:
                        break

            except Exception as e:
                logger.error(f"Connection error: {e}")
            finally:
                # Avoid busy reconnection
                await asyncio.sleep(self.reconnect_delay)

    async def _receiver(self, ws: websockets.WebSocketClientProtocol):
        """Receive loop: handles incoming messages and updates proxies."""
        try:
            async for message in ws:
                data = json.loads(message)
                action = data.get("action")
                
                if action == "proxy_available":
                    proxy = data.get("proxy")
                    source_id = data.get("source_id", self.source_ids[0] if self.source_ids else "1")
                    usage_interval = data.get("usage_interval", 30)
                    
                    if proxy:
                        async with self._lock:
                            # Add to the appropriate source list
                            if source_id not in self.proxies_by_source:
                                self.proxies_by_source[source_id] = []
                            
                            # Save the usage_interval with the proxy
                            proxy['usage_interval'] = usage_interval
                            proxy['_in_use'] = False  # Track usage status
                            
                            # Check if proxy already exists
                            proxy_id = proxy.get('id')
                            exists = False
                            for i, p in enumerate(self.proxies_by_source[source_id]):
                                if p.get('id') == proxy_id:
                                    # Update the existing proxy but preserve _in_use status
                                    was_in_use = p.get('_in_use', False)
                                    self.proxies_by_source[source_id][i] = proxy
                                    self.proxies_by_source[source_id][i]['_in_use'] = was_in_use
                                    exists = True
                                    break
                            
                            if not exists:
                                self.proxies_by_source[source_id].append(proxy)
                                logger.info(f"New proxy: {proxy_id} from source {source_id}, interval: {usage_interval}s")
                            
                        # Request another proxy to keep the pool filled
                        await ws.send(json.dumps({"action": "request_proxy"}))
                
                elif action == "proxy_in_use":
                    # Server notifies that a proxy is being used by another client
                    proxy_id = data.get("proxy_id")
                    usage_interval = data.get("usage_interval", 30)
                    
                    if proxy_id:
                        async with self._lock:
                            # Mark this proxy as in use until the specified time
                            self.in_use_proxies[proxy_id] = time.time() + usage_interval
                            
                            # Find and mark the proxy in its source list
                            for src, proxies in self.proxies_by_source.items():
                                for i, proxy in enumerate(proxies):
                                    if proxy.get('id') == proxy_id:
                                        self.proxies_by_source[src][i]['_in_use'] = True
                                        logger.info(f"Proxy {proxy_id} from source {src} is now BLOCKED for {usage_interval}s")
                                        break
                
                elif action == "waiting":
                    logger.debug("Server waiting for proxies")
                
                elif action == "report_acknowledged":
                    pid = data.get("proxy_id")
                    ok = data.get("success", False)
                    logger.info(f"Report ack for proxy {pid}: {'OK' if ok else 'FAIL'}")
                
                elif action == "error":
                    logger.error(f"Server error: {data.get('message')}")
        
        except ConnectionClosed:
            logger.warning("WebSocket closed by server")
        except Exception as e:
            logger.error(f"Receiver error: {e}")

    async def _sender(self, ws: websockets.WebSocketClientProtocol):
        """Send loop: drains outgoing queue and sends messages."""
        try:
            while True:
                msg = await self._outgoing.get()
                await ws.send(json.dumps(msg))
                self._outgoing.task_done()
                logger.info(f"Sent message: {msg}")
        except ConnectionClosed:
            logger.warning("WebSocket closed during send")
        except Exception as e:
            logger.error(f"Sender error: {e}")


# Example usage:
async def main():
    # Load API key from environment or configuration
    api_key = os.environ.get("SECRET")
    
    # Create client with sources 1 and 2
    client = ProxyClient("ws://66.45.254.69:8000", ["1"], api_key=api_key)
    
    # Start the background connection
    client.start()
    
    # Wait for some proxies to be received
    await asyncio.sleep(2)
    
    import random
    import time
    test_time = 100 # seconds
    # Get a proxy from source 1
    start_time = time.time()
    while time.time() - start_time < test_time:
        proxy = await client.get_proxy("1")
        
        if proxy:
            usage_interval = proxy.get('usage_interval', 30)
            proxy_id = proxy.get('id')
            proxy_address = proxy.get('proxy')
            print(f"Got proxy: {proxy_id} (blocked for {usage_interval}s)")
            print(f"Proxy address: {proxy_address}")
            
            # Display status information
            status = client.get_proxy_status(proxy_id)
            print(f"Status: Blocked for {status['time_remaining']:.1f} seconds")
            
            # Send a report for this proxy
            await client.send_report(proxy_id, 200)
            await asyncio.sleep(random.randint(1, 3))

        else:
            # Show which proxies are currently blocked
            all_status = client.get_all_proxies_status()
            blocked_proxies = []
            recently_used = []
            
            for src, proxies in all_status.items():
                for p in proxies:
                    if p['in_use']:
                        blocked_proxies.append(f"ID {p['id']} (remaining: {p['time_remaining']:.1f}s)")
                    elif p['last_used'] < client.reuse_delay:
                        recently_used.append(f"ID {p['id']} (used {p['last_used']:.1f}s ago)")
            
            if blocked_proxies:
                print(f"No proxy available - blocked proxies: {', '.join(blocked_proxies)}")
            if recently_used:
                print(f"Recently used (cooling down): {', '.join(recently_used)}")
            if not blocked_proxies and not recently_used:
                print("No proxy available - no proxies in pool")
                
            await asyncio.sleep(0.3)
        
        print(f"Time elapsed: {time.time() - start_time} seconds")
        print("-" * 40)
            
    await client.stop()

if __name__ == '__main__':
    # Make sure to set the API_KEY environment variable or replace with actual key
    asyncio.run(main())