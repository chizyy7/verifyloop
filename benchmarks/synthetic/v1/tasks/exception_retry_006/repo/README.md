# Retry decorator performs one attempt too few

resilience.py provides a retry decorator. Its docstring states that ``times`` is the total number of attempts, but the loop currently runs one attempt fewer than requested, so retry(times=1) never calls the function at all and retry(times=3) only makes two attempts. Fix the loop, preserve the behaviour that the last exception is re-raised when all attempts fail, and keep non-matching exceptions propagating immediately.
