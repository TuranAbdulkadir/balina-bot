import asyncio
import time
from core.logger_factory import get_logger
logger = get_logger("Watchdog")

import multiprocessing
import sys

async def watchdog_task(brain_proc: multiprocessing.Process, tolerance_sec: float = 0.1):
    """
    Monitors the event loop for blocking operations.
    If the loop is blocked for more than `tolerance_sec` (Default: 100ms),
    a warning is logged.
    """
    logger.info(f"Watchdog started with {tolerance_sec*1000:.0f}ms tolerance.")
    while True:
        start = time.monotonic()
        # Uyku süresi toleransın en fazla 1/10'u kadar olmalıdır ki hassas ölçüm yapılabilsin.
        await asyncio.sleep(0.01)
        
        delay = time.monotonic() - start - 0.01
        if delay > tolerance_sec:
            logger.warning(f"Loop blocked! Delay: {delay*1000:.2f} ms")
            
        if brain_proc and not brain_proc.is_alive():
            logger.critical("FATAL: Quantitative Brain Multiprocessing Core DIED! Zombie-state prevented. Bailing out for PM2 rescue.")
            sys.exit(1)
