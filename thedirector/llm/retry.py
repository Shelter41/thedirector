import asyncio
import functools
import logging
import random

logger = logging.getLogger("thedirector.retry")


def retry_async(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_retries + 1,
                            e,
                        )
                        raise
                    actual_delay = delay
                    if jitter:
                        actual_delay *= random.uniform(0.5, 1.0)
                    logger.warning(
                        "%s attempt %d/%d failed: %s. Retrying in %.1fs",
                        func.__name__,
                        attempt + 1,
                        max_retries + 1,
                        e,
                        actual_delay,
                    )
                    await asyncio.sleep(actual_delay)
                    delay = min(delay * backoff_factor, max_delay)
            raise last_exception

        return wrapper

    return decorator
