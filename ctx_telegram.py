import asyncio
import multiprocessing
from network.telegram_bot import TelegramBot
from core.config import TG_TOKEN, TELEGRAM_ALLOWED_USER_ID

def telegram_worker(tg_queue: multiprocessing.Queue):
    """
    Isolated process entry point for Telegram bot.
    """
    bot = TelegramBot(
        token=TG_TOKEN or "",
        allowed_user=TELEGRAM_ALLOWED_USER_ID or "",
        tg_queue=tg_queue
    )
    
    asyncio.run(bot.poll())
