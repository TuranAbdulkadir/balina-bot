import aiosqlite
import asyncio
from core.logger_factory import get_logger
logger = get_logger("Database")

class SQLiteStore:
    """High-speed asynchronous robust SQLite optimized for HFT environments using WAL mode."""
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.queue = asyncio.Queue()
        self.batch_size = 100
        self.flush_interval = 2.0
        self._connection = None

    async def init_db(self):
        self._connection = await aiosqlite.connect(self.db_path)
        # Disk IO bottleneck prevention params
        await self._connection.execute("PRAGMA journal_mode=WAL;")
        await self._connection.execute("PRAGMA synchronous=NORMAL;")
        
        # Minimalist high-speed storage table
        await self._connection.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price REAL,
                qty REAL,
                is_buyer_maker INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await self._connection.commit()
        
        # Spawn daemon tasks
        asyncio.create_task(self._writer_loop())
        asyncio.create_task(self._wal_checkpoint_loop())
        logger.info("Database WAL initialized securely.")

    async def insert_trade(self, price: float, qty: float, is_buyer_maker: bool):
        """Asynchronous injection avoiding main loop blocking."""
        await self.queue.put((price, qty, int(is_buyer_maker)))

    async def _writer_loop(self):
        """Batches inserts efficiently."""
        while True:
            batch = []
            try:
                while len(batch) < self.batch_size:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                    batch.append(item)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
                
            if batch:
                try:
                    await self._connection.executemany(
                        "INSERT INTO trades (price, qty, is_buyer_maker) VALUES (?, ?, ?)",
                        batch
                    )
                    await self._connection.commit()
                except Exception as e:
                    logger.error(f"DB Write Error: {e}")

    async def _wal_checkpoint_loop(self):
        """Prevents disk from bloating by routinely truncating WAL segments."""
        while True:
            await asyncio.sleep(3600)  # Sweep every hour
            try:
                await self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                logger.info("Executed SQLite WAL CHECKPOINT TRUNCATE. Disk optimized.")
            except Exception as e:
                logger.error(f"WAL Checkpoint Error: {e}")
