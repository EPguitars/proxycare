import redis

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, db=0)

def store_data(source_id, proxy_address):
    # Add the proxy address to a list stored under the source_id key
    r.lpush(source_id, proxy_address)

def get_and_delete_proxy_for_source(source_id):
    # Retrieve and remove the first proxy address from the list
    return r.lpop(source_id)

# Example usage:
# store_data('source1', 'proxy1')
# store_data('source1', 'proxy2')
x = get_and_delete_proxy_for_source('source1')

print(type(x))
result = x and x.decode('utf-8')
print(result)
print(type(result))

