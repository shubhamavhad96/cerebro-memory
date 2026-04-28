import time
import threading


class TokenBucketRateLimiter:
    """
    @entity: TokenBucketLimiter
    @decision: Using Token Bucket over Fixed Window to allow for controlled bursts 
               while maintaining a steady long-term rate.
    """

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.time()
        delta = now - self.last_refill
        # Formula: tokens = min(capacity, tokens + (delta * rate))
        added_tokens = delta * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + added_tokens)
        self.last_refill = now

    def consume(self, amount: int = 1) -> bool:
        with self.lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False


# Example Usage
if __name__ == "__main__":
    # 10 tokens capacity, refills 1 token per second
    limiter = TokenBucketRateLimiter(10, 1)

    for i in range(12):
        if limiter.consume(1):
            print(f"Request {i+1}: Allowed")
        else:
            print(f"Request {i+1}: Rate Limited")
        time.sleep(0.5)
