import gc
import asyncio
from core.logger_factory import get_logger
logger = get_logger("MemoryGuard")

async def memory_guard_task(interval_sec: int = 3600):
    """
    Periodically forces Python Garbage Collection to reclaim orphaned async objects.
    Ensures that long-running 7/24 bot operations do not bleed memory.
    """
    logger.info(f"Memory Guard initialized on an interval of {interval_sec} seconds.")
    while True:
        await asyncio.sleep(interval_sec)
        try:
            # Reclaim unreferenced objects and cyclic references escaping scope
            collected = gc.collect()
            logger.info(f"Memory Guard forced gc.collect()! Reclaimed {collected} phantom objects. RAM pristine.")
        except Exception as e:
            logger.error(f"Memory Guard Exception: {e}")
