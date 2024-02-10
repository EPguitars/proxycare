"""Proxy factory"""
import time
import threading

from rich import print

from config import shops
from proxies import proxies


class ProxyFactory:
    """Proxy factory"""

    def __init__(self, proxies):
        self.proxies = proxies

    def get_proxies(self):
        print(self.proxies)

    def _move_query(self):
        """Move query to the end of the queue"""
        first_key, first_value = next(iter(self.proxies.items()))
        # Remove the first key-value pair from the dictionary
        self.proxies.pop(first_key)
        # Re-insert the first key-value pair at the end of the dictionary
        self.proxies[first_key] = first_value

    def _change_status(self, key, status):
        """Change status of a proxy"""
        self.proxies[key] = status
    
    def schedule_status(self, key, status, interval):
        """Schedule status of a proxy"""
        time.sleep(interval)
        self.proxies[key] = status

    def get_proxy(self, interval=5):
        """Get a proxy"""
        proxy_dict = next(iter(self.proxies.items()))
        
        if proxy_dict[1] == False:
            return "No proxies available"
        
        else:
            proxy = proxy_dict[0]
            self._change_status(proxy, False)
            self._move_query()
            return_true = threading.Thread(target=self.schedule_status, args=(proxy, True, interval), daemon=True)
            return_true.start()

            return proxy
        


def create_instances():
    """Create instances of proxies"""
    result = dict()

    for shop in shops:
        result[shop] = ProxyFactory(proxies)
    print("Proxy storage generated")
    return result


proxy_storage = create_instances()