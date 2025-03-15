# app/utils/cache.py
import redis

# Configure Redis connection (update host/port as needed)
redis_client = redis.Redis(
    host="localhost", 
    port=6379, 
    db=0, 
    decode_responses=True
)
