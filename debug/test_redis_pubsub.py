"""
debug/test_redis_pubsub.py

Diagnostic test to verify Redis pub/sub is working correctly.
Run this to test if the issue is in Redis itself or in the event bus implementation.
"""

import redis
import time
import threading

def test_redis_pubsub():
    """Test basic Redis pub/sub functionality."""
    
    print("=" * 60)
    print("REDIS PUB/SUB DIAGNOSTIC TEST")
    print("=" * 60)
    
    # Connect to Redis
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Connected to Redis at localhost:6379")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return
    
    # Test channel
    test_channel = 'test_rtd_sim_channel'
    messages_received = []
    
    # Subscriber function
    def subscriber():
        sub = redis.Redis(host='localhost', port=6379, db=0)
        pubsub = sub.pubsub()
        pubsub.subscribe(test_channel)
        
        print(f"🎧 Subscriber listening on channel: {test_channel}")
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                data = message['data'].decode('utf-8')
                print(f"   📨 Received: {data}")
                messages_received.append(data)
                
                if data == 'STOP':
                    break
    
    # Start subscriber in thread
    sub_thread = threading.Thread(target=subscriber, daemon=True)
    sub_thread.start()
    
    # Give subscriber time to connect
    time.sleep(0.5)
    
    # Publish messages
    print(f"\n📢 Publishing messages to channel: {test_channel}")
    for i in range(5):
        message = f"Test message {i+1}"
        r.publish(test_channel, message)
        print(f"   📤 Published: {message}")
        time.sleep(0.1)
    
    # Stop subscriber
    r.publish(test_channel, 'STOP')
    time.sleep(0.5)
    
    # Results
    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"   Messages published: 5")
    print(f"   Messages received: {len(messages_received)}")
    
    if len(messages_received) == 5:
        print("   ✅ SUCCESS: Redis pub/sub is working correctly!")
    else:
        print(f"   ❌ FAILED: Only received {len(messages_received)}/5 messages")
        print(f"   This indicates a Redis pub/sub issue")
    
    print("=" * 60)


if __name__ == '__main__':
    test_redis_pubsub()