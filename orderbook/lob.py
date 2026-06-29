from collections import deque
from core.logger_factory import get_logger
from typing import Dict

logger = get_logger("LOB")

class OrderBookState:
    __slots__ = ["bids", "asks", "last_update_id"]
    
    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_update_id: int = 0
        
class MarkPriceTracker:
    __slots__ = ["mark_price", "index_price", "funding_rate"]
    
    def __init__(self):
        self.mark_price: float = 0.0
        self.index_price: float = 0.0
        self.funding_rate: float = 0.0

class LimitOrderBook:
    __slots__ = ["symbol", "state", "mark", "syncing", "buffer", "prune_ticks"]
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.state = OrderBookState()
        self.mark = MarkPriceTracker()
        self.syncing = True
        self.buffer: deque = deque(maxlen=2000)
        self.prune_ticks = 0

    def process_snapshot(self, snapshot: dict):
        """Initializes the LOB with REST snapshot and flushes the WS Buffer."""
        self.state.last_update_id = snapshot.get("lastUpdateId", 0)
        self.state.bids.clear()
        self.state.asks.clear()
        
        for bid in snapshot.get("bids", []):
            self.state.bids[float(bid[0])] = float(bid[1])
        for ask in snapshot.get("asks", []):
            self.state.asks[float(ask[0])] = float(ask[1])
            
        logger.info(f"[{self.symbol}] LOB Snapshot Applied. Baseline LastUpdateId: {self.state.last_update_id}. Processing {len(self.buffer)} buffered WS ticks...")
        
        self.syncing = False
        
        # Re-play buffer to catch up to real-time safely
        valid_events = 0
        for event in self.buffer:
            u = event.get("u", 0)
            if u > self.state.last_update_id:
                # We do not strictly check is_first_event_overlap during buffer playback
                # because the event was captured simultaneously. We apply it to close the timeline gap.
                self._apply_diff_raw(event)
                valid_events += 1
                
        self.buffer.clear()
        logger.info(f"[{self.symbol}] Re-Sync Sequence complete. Processed {valid_events} valid buffered events. Motor is now live.")

    def process_diff(self, event: dict):
        """Processes WS diff updates (depthUpdate event). Routes to buffer if Syncing."""
        if self.syncing:
            self.buffer.append(event)
            return
        
        u = event.get("u", 0)
        U = event.get("U", 0)
        pu = event.get("pu", 0)
        
        if u <= self.state.last_update_id:
            return
            
        is_first_event_overlap = (U <= self.state.last_update_id) and (u >= self.state.last_update_id)
        
        if self.state.last_update_id > 0:
            if not is_first_event_overlap and pu > 0 and pu != self.state.last_update_id:
                logger.warning(f"[{self.symbol}] LOB GAP DETECTED! Expected pu={self.state.last_update_id}, got pu={pu}, U={U}. Triggering re-sync.")
                self.syncing = True
                self.buffer.clear()
                self.buffer.append(event)
                return
            
        self._apply_diff_raw(event)
        
    def _apply_diff_raw(self, event: dict):
        """Applies depth mutations linearly assuming timeline is validated."""
        for bid in event.get("b", []):
            price = float(bid[0])
            qty = float(bid[1])
            if qty == 0:
                self.state.bids.pop(price, None)
            else:
                self.state.bids[price] = qty
                
        for ask in event.get("a", []):
            price = float(ask[0])
            qty = float(ask[1])
            if qty == 0:
                self.state.asks.pop(price, None)
            else:
                self.state.asks[price] = qty

        self.state.last_update_id = event.get("u", self.state.last_update_id)
        
        # Phase 28.7: Limit Order Book Memory Garbage Collection
        self.prune_ticks += 1
        bb = self.get_best_bid()
        ba = self.get_best_ask()
        
        if self.prune_ticks >= 2000:
            self.prune_ticks = 0
            if bb > 0 and ba > 0:
                mid_price = (bb + ba) / 2.0
                upper_bound = mid_price * 1.15
                lower_bound = mid_price * 0.85
                
                # Prune old bids
                stale_bids = [p for p in self.state.bids if p < lower_bound]
                for p in stale_bids:
                    del self.state.bids[p]
                    
                # Prune old asks
                stale_asks = [p for p in self.state.asks if p > upper_bound]
                for p in stale_asks:
                    del self.state.asks[p]
        
        # 9. LOB Cross-Matching Risk Immunity
        if bb > 0.0 and ba > 0.0 and bb >= ba:
            logger.critical(f"⚠️ LOB CROSS-MATCH DETECTED: {bb} >= {ba}. Binance UDP desync suspected. Hard resync triggered.")
            self.syncing = True
        
    def process_mark_price(self, event: dict):
        self.mark.mark_price = float(event.get("p", self.mark.mark_price))
        self.mark.index_price = float(event.get("i", self.mark.index_price))
        self.mark.funding_rate = float(event.get("r", self.mark.funding_rate))

    def get_best_bid(self) -> float:
        return max(self.state.bids.keys()) if self.state.bids else 0.0

    def get_best_ask(self) -> float:
        return min(self.state.asks.keys()) if self.state.asks else 0.0

    def get_order_book_imbalance(self, top_n: int = 10) -> float:
        if not self.state.bids or not self.state.asks:
            return 0.0
            
        sorted_bids = sorted(self.state.bids.keys(), reverse=True)[:top_n]
        top_bid_vol = sum(self.state.bids[k] for k in sorted_bids)
        
        sorted_asks = sorted(self.state.asks.keys())[:top_n]
        top_ask_vol = sum(self.state.asks[k] for k in sorted_asks)
        
        total_vol = top_bid_vol + top_ask_vol
        if total_vol == 0:
            return 0.0
            
        return (top_bid_vol - top_ask_vol) / total_vol

    def simulate_market_order(self, side: str, qty: float) -> float:
        """
        AŞAMA 19 (Görev 4): Girilen miktar icin LOB kademelerini yiyerek (VWAP)
        gerceklesecek ortalama fiyati (slippage dahil) dondurur.
        """
        if qty <= 0:
            return self.get_best_ask() if side == "BUY" else self.get_best_bid()
            
        remaining = qty
        total_cost = 0.0
        
        if side == "BUY":
            sorted_asks = sorted(self.state.asks.items())
            for price, vol in sorted_asks:
                fill_qty = min(remaining, vol)
                total_cost += price * fill_qty
                remaining -= fill_qty
                if remaining <= 0:
                    break
            if remaining > 0:
                worst_price = sorted_asks[-1][0] if sorted_asks else self.get_best_ask()
                total_cost += (worst_price * 1.01) * remaining
                
        elif side == "SELL":
            sorted_bids = sorted(self.state.bids.items(), reverse=True)
            for price, vol in sorted_bids:
                fill_qty = min(remaining, vol)
                total_cost += price * fill_qty
                remaining -= fill_qty
                if remaining <= 0:
                    break
            if remaining > 0:
                worst_price = sorted_bids[-1][0] if sorted_bids else self.get_best_bid()
                total_cost += (worst_price * 0.99) * remaining
                
        return total_cost / qty
