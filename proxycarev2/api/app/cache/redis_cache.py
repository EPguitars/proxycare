import redis
from typing import Dict, List, Optional, Any
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Proxy, Source, Provider
import logging

logger = logging.getLogger(__name__)

class RedisCache:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisCache, cls).__new__(cls)
            cls._instance._connect()
        return cls._instance
    
    def _connect(self):
        """Establish connection to Redis"""
        self.redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            password=settings.REDIS_PASSWORD,
            db=int(settings.REDIS_DB),
            decode_responses=True  # Return strings instead of bytes
        )
        try:
            self.redis.ping()
            logger.info("Successfully connected to Redis")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            # We don't want to raise an exception here to allow the app to start
            # even if Redis is temporarily unavailable
    
    def load_all_proxies(self):
        """Load all proxies from the database into Redis cache"""
        try:
            db = SessionLocal()
            proxies = db.query(Proxy).all()
            
            # Create a pipeline for batch operations
            pipe = self.redis.pipeline()
            
            # Clear existing proxies cache
            pipe.delete("proxies:all")
            
            # Store each proxy in the cache
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
                    "updatedAt": proxy.updatedat.isoformat() if proxy.updatedat else None
                }
                
                # Add to a list of all proxies
                pipe.rpush("proxies:all", json.dumps(proxy_data))
                
                # Also store by ID for quick lookups
                pipe.set(f"proxy:{proxy.id}", json.dumps(proxy_data))
                
                # Store by source for filtered queries
                if proxy.sourceid:
                    pipe.rpush(f"proxies:source:{proxy.sourceid}", json.dumps(proxy_data))
                
                # Store by priority range for quick access to high priority proxies
                if proxy.priority:
                    # Group priorities (e.g., 90-100, 80-89, etc.)
                    priority_group = proxy.priority // 10 * 10
                    pipe.rpush(f"proxies:priority:{priority_group}", json.dumps(proxy_data))
            
            # Execute all commands in the pipeline
            pipe.execute()
            
            logger.info(f"Loaded {len(proxies)} proxies into Redis cache")
            return len(proxies)
        except Exception as e:
            logger.error(f"Error loading proxies into cache: {e}")
            return 0
        finally:
            db.close()
    
    def get_all_proxies(self) -> List[Dict[str, Any]]:
        """Get all proxies from Redis cache"""
        try:
            proxy_data = self.redis.lrange("proxies:all", 0, -1)
            return [json.loads(data) for data in proxy_data]
        except Exception as e:
            logger.error(f"Error retrieving proxies from cache: {e}")
            return []
    
    def get_proxy_by_id(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific proxy by ID"""
        try:
            proxy_data = self.redis.get(f"proxy:{proxy_id}")
            if proxy_data:
                return json.loads(proxy_data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving proxy {proxy_id} from cache: {e}")
            return None
    
    def get_proxies_by_source(self, source_id: int) -> List[Dict[str, Any]]:
        """Get all proxies for a specific source"""
        try:
            proxy_data = self.redis.lrange(f"proxies:source:{source_id}", 0, -1)
            return [json.loads(data) for data in proxy_data]
        except Exception as e:
            logger.error(f"Error retrieving proxies for source {source_id}: {e}")
            return []
    
    def get_proxy_by_source_id(self, source_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific proxy by source ID"""
        try:
            # We'll get the first proxy from the list for this source
            proxies = self.get_proxies_by_source(source_id)
            if proxies:
                return proxies[0]
            return None
        except Exception as e:
            logger.error(f"Error retrieving proxy by source {source_id} from cache: {e}")
            return None
    
    def get_high_priority_proxies(self, min_priority: int = 90) -> List[Dict[str, Any]]:
        """Get high priority proxies (default: priority >= 90)"""
        try:
            # Find what priority groups we need to fetch
            priority_groups = []
            current_group = min_priority // 10 * 10
            while current_group <= 100:  # Assuming 100 is max priority
                priority_groups.append(current_group)
                current_group += 10
            
            result = []
            for group in priority_groups:
                proxy_data = self.redis.lrange(f"proxies:priority:{group}", 0, -1)
                result.extend([json.loads(data) for data in proxy_data])
            
            # Filter results to match the exact minimum priority
            return [proxy for proxy in result if proxy.get('priority', 0) >= min_priority]
        except Exception as e:
            logger.error(f"Error retrieving high priority proxies: {e}")
            return []
    
    def update_proxy(self, proxy_id: int, update_data: dict) -> bool:
        """Update specific fields of a proxy in the cache"""
        try:
            # Get the current proxy data
            proxy_data = self.get_proxy_by_id(proxy_id)
            if not proxy_data:
                logger.error(f"Proxy {proxy_id} not found in cache")
                return False
            
            # Update the fields
            proxy_data.update(update_data)
            
            # Update in Redis
            pipe = self.redis.pipeline()
            
            # Update by ID
            pipe.set(f"proxy:{proxy_id}", json.dumps(proxy_data))
            
            # Update in source list if it exists
            source_id = proxy_data.get('sourceId')
            if source_id:
                # Get all proxies for this source
                source_proxies = self.get_proxies_by_source(source_id)
                if source_proxies:
                    # Find the index of this proxy in the list
                    for i, proxy in enumerate(source_proxies):
                        if proxy.get('id') == proxy_id:
                            # Update the proxy at this index
                            source_proxies[i] = proxy_data
                            break
                    
                    # Clear and recreate the source list
                    pipe.delete(f"proxies:source:{source_id}")
                    for proxy in source_proxies:
                        pipe.rpush(f"proxies:source:{source_id}", json.dumps(proxy))
            
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Error updating proxy {proxy_id} in cache: {e}")
            return False
    
    def clear_cache(self) -> bool:
        """Clear all proxy data from the cache"""
        try:
            # Get all keys matching our proxy patterns
            keys = self.redis.keys("proxy:*") + self.redis.keys("proxies:*")
            if keys:
                self.redis.delete(*keys)
            logger.info("Cleared proxy cache")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    def refresh_cache(self) -> int:
        """Refresh the entire proxy cache from the database"""
        self.clear_cache()
        return self.load_all_proxies()
    
    def delete_proxy(self, proxy_id: int, source_id: str = None) -> bool:
        """Delete a proxy from the cache"""
        try:
            # Get the proxy data first
            proxy_data = self.get_proxy_by_id(proxy_id)
            if not proxy_data:
                logger.warning(f"Proxy {proxy_id} not found in cache for deletion")
                return False
            
            # Use pipeline for atomic operations
            pipe = self.redis.pipeline()
            
            # Delete the proxy by ID
            pipe.delete(f"proxy:{proxy_id}")
            
            # If source_id is provided, remove from that source's list
            if source_id:
                # Get all proxies for this source
                source_proxies = self.get_proxies_by_source(source_id)
                if source_proxies:
                    # Filter out the proxy to delete
                    updated_proxies = [p for p in source_proxies if p.get('id') != proxy_id]
                    
                    # Clear and recreate the source list
                    pipe.delete(f"proxies:source:{source_id}")
                    for proxy in updated_proxies:
                        pipe.rpush(f"proxies:source:{source_id}", json.dumps(proxy))
            
            # Execute all commands
            pipe.execute()
            logger.info(f"Deleted proxy {proxy_id} from cache")
            return True
        
        except Exception as e:
            logger.error(f"Error deleting proxy {proxy_id} from cache: {e}")
            return False 