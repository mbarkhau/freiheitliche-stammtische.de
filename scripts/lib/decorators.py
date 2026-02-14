import time
import functools as ft
import typing as typ

_last_call_times: dict[str, float] = {}

def rate_limit(min_interval: float = 1.0):
    """Decorator that ensures a minimum interval between function calls.

    This is useful for API calls that have rate limits.
    """
    def decorator(func: typ.Callable):
        @ft.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal min_interval
            func_id = f"{func.__module__}.{func.__name__}"
            
            last_call = _last_call_times.get(func_id, 0)
            elapsed = time.time() - last_call
            wait = min_interval - elapsed
            
            if wait > 0:
                time.sleep(wait)
            
            result = func(*args, **kwargs)
            _last_call_times[func_id] = time.time()
            return result
        return wrapper
    return decorator
