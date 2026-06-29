import logging
import multiprocessing
from core.logger_factory import get_logger
from core.zscore import RollingZScore
from core.vpin import VPIN

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] PROCESS-%(process)d: %(message)s")
logger = get_logger("Brain")

def brain_worker(data_queue: multiprocessing.Queue, signal_queue: multiprocessing.Queue):
    """
    Dedicated OS-level multiprocessing core.
    Freed entirely from the event loop, computes quantitative logic
    at microsecond speeds and emits signals back to the main process.
    """
    zscore_engine = RollingZScore(window_size=3000)
    vpin_engine = VPIN(bucket_size=50.0, vpin_threshold=0.75)
    
    # ── AŞAMA 19: WARM START (Data Lake Persist) ──
    try:
        import os
        import glob
        import pandas as pd
        files = glob.glob("core/data_lake/*.parquet")
        if files:
            latest_file = max(files, key=os.path.getmtime)
            df = pd.read_parquet(latest_file)
            df = df.tail(3000)
            for _, row in df.iterrows():
                mid_price = (row["best_bid"] + row["best_ask"]) / 2.0
                zscore_engine.add_price(mid_price)
            logger.info(f"🧠 Z-Score Warm Start basarili: {len(df)} gecmis fiyat {latest_file} uzerinden yuklendi.")
    except Exception as e:
        logger.warning(f"Brain warm start atlandi (Hata veya dosya yok): {e}")

    logger.info("Brain Multiprocessing Core initialized and ready.")
    
    while True:
        try:
            payload = data_queue.get()
            if payload is None:
                logger.info("Brain Shutdown signal received.")
                break
                
            msg_type = payload[0]
            
            if msg_type == "TRADE":
                price = payload[1]
                qty = payload[2]
                is_buyer_maker = payload[3]
                
                # VPIN Analysis
                is_toxic = vpin_engine.add_trade(qty, is_buyer_maker)
                try:
                    if is_toxic:
                        logger.warning("VPIN TOXIC: Unilateral aggressive selling detected!")
                        signal_queue.put_nowait(("TOXIC_FLOW_FLAG", True))
                    else:
                        signal_queue.put_nowait(("TOXIC_FLOW_FLAG", False))
                except multiprocessing.queues.Full:
                    pass
                
                # Z-Score Computation
                z = zscore_engine.add_price(price)
                
                try:
                    signal_queue.put_nowait(("ZSCORE", float(z)))
                    signal_queue.put_nowait(("VPIN", float(vpin_engine.vpin)))
                except multiprocessing.queues.Full:
                    pass
                
            elif msg_type == "OBI":
                obi_val = payload[1]
                try:
                    signal_queue.put_nowait(("OBI", float(obi_val)))
                except multiprocessing.queues.Full:
                    pass
                
        except Exception as e:
            logger.error(f"Brain execution encountered exception: {e}")
