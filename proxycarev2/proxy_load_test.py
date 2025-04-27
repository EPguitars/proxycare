import asyncio
import json
import logging
import os
import time
import random
from typing import Dict, List, Optional
import websockets
from websockets.exceptions import ConnectionClosed
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ProxyLoadTest:
    def __init__(self, base_url: str, api_key: str, connections: int = 10, 
                 test_duration: int = 60, source_ids: List[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.connections = connections
        self.test_duration = test_duration
        self.source_ids = source_ids or ["1"]
        
        # Stats tracking
        self.proxies_received = 0
        self.connection_errors = 0
        self.authentication_errors = 0
        self.successful_connections = 0
        self.reports_sent = 0
        self.reports_acknowledged = 0
        
        # Connection tracking
        self._active_tasks = []
        self._stop_event = asyncio.Event()

    async def run(self):
        """Run the load test with multiple connections"""
        start_time = time.time()
        logger.info(f"Starting load test with {self.connections} connections for {self.test_duration} seconds")
        
        # Create and start connection tasks
        for i in range(self.connections):
            task = asyncio.create_task(self._connection_worker(i))
            self._active_tasks.append(task)
            # Stagger connections slightly to avoid overwhelming the server
            await asyncio.sleep(0.1)
        
        # Wait for test duration
        await asyncio.sleep(self.test_duration)
        
        # Signal workers to stop
        logger.info("Test duration reached, stopping connections...")
        self._stop_event.set()
        
        # Wait for all tasks to complete
        await asyncio.gather(*self._active_tasks, return_exceptions=True)
        
        # Report results
        test_duration = time.time() - start_time
        logger.info("-" * 50)
        logger.info(f"Load Test Results (Duration: {test_duration:.2f}s):")
        logger.info(f"  Connections attempted: {self.connections}")
        logger.info(f"  Successful connections: {self.successful_connections}")
        logger.info(f"  Connection errors: {self.connection_errors}")
        logger.info(f"  Authentication errors: {self.authentication_errors}")
        logger.info(f"  Proxies received: {self.proxies_received}")
        logger.info(f"  Proxies per second: {self.proxies_received / test_duration:.2f}")
        logger.info(f"  Reports sent: {self.reports_sent}")
        logger.info(f"  Reports acknowledged: {self.reports_acknowledged}")
        logger.info("-" * 50)

    async def _connection_worker(self, connection_id: int):
        """Individual connection worker that requests and processes proxies"""
        logger.info(f"Starting connection {connection_id}")
        
        # Select random source from available sources
        source_id = random.choice(self.source_ids)
        ws_url = f"{self.base_url}/ws/proxy_multi?token={self.api_key}"
        
        try:
            async with websockets.connect(ws_url) as ws:
                # Successfully connected
                self.successful_connections += 1
                logger.info(f"Connection {connection_id} established")
                
                # Send start message with source IDs
                start_msg = {"action": "start", "source_ids": [source_id]}
                await ws.send(json.dumps(start_msg))
                
                # Process messages until stop event is set
                while not self._stop_event.is_set():
                    try:
                        # Set a timeout to regularly check the stop event
                        message_json = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        message = json.loads(message_json)
                        
                        action = message.get('action')
                        
                        if action == 'proxy_available':
                            # Got a proxy
                            self.proxies_received += 1
                            proxy = message.get('proxy', {})
                            proxy_id = proxy.get('id')
                            
                            if proxy_id:
                                # Send a report for this proxy
                                report = {
                                    "action": "report_proxy",
                                    "proxy_id": proxy_id,
                                    "status_code": random.choice([200, 403, 429, 503])  # Simulate different statuses
                                }
                                await ws.send(json.dumps(report))
                                self.reports_sent += 1
                                
                                # Notify other clients this proxy is in use
                                usage_interval = message.get('usage_interval', 30)
                                await ws.send(json.dumps({
                                    "action": "proxy_taken",
                                    "proxy_id": proxy_id,
                                    "usage_interval": usage_interval
                                }))
                                
                                # Simulate using the proxy for a random time
                                await asyncio.sleep(random.uniform(0.2, 1.0))
                            
                        elif action == 'report_acknowledged':
                            self.reports_acknowledged += 1
                            
                        elif action == 'error':
                            error_msg = message.get('message', 'Unknown error')
                            if 'authentication' in error_msg.lower():
                                self.authentication_errors += 1
                                logger.error(f"Connection {connection_id}: Authentication error: {error_msg}")
                                break
                            else:
                                logger.warning(f"Connection {connection_id}: Error: {error_msg}")
                        
                        elif action == 'waiting':
                            # No proxies available, wait a bit
                            await asyncio.sleep(0.5)
                            
                    except asyncio.TimeoutError:
                        # Just a timeout to check stop event, continue
                        continue
                    except ConnectionClosed:
                        logger.warning(f"Connection {connection_id} was closed by server")
                        break
        
        except Exception as e:
            self.connection_errors += 1
            logger.error(f"Connection {connection_id} error: {str(e)}")
        
        logger.info(f"Connection {connection_id} worker finished")

async def main():
    parser = argparse.ArgumentParser(description="WebSocket Proxy Load Testing Tool")
    parser.add_argument('--url', default='ws://localhost:8000', help='WebSocket server URL')
    parser.add_argument('--connections', type=int, default=10, help='Number of concurrent connections')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in seconds')
    parser.add_argument('--sources', default='1,2', help='Comma-separated list of source IDs')
    args = parser.parse_args()
    
    # Get API key from environment
    api_key = os.environ.get("SECRET")
    if not api_key:
        logger.error("No SECRET environment variable found. Please set it first.")
        return
    
    sources = args.sources.split(',')
    
    # Run the load test
    test = ProxyLoadTest(
        base_url=args.url,
        api_key=api_key,
        connections=args.connections,
        test_duration=args.duration,
        source_ids=sources
    )
    
    await test.run()

if __name__ == '__main__':
    asyncio.run(main())