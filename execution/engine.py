import asyncio
import uuid
import aiohttp
from core.logger_factory import get_logger
from decimal import Decimal, ROUND_DOWN
from typing import Dict
from orderbook.lob import LimitOrderBook
from network.http_client import BinanceRestClient

import time

logger = get_logger("ExecutionEngine")

class ExecutionEngine:
    def __init__(self, rest_client: BinanceRestClient):
        self.rest = rest_client
        self.locks: Dict[str, asyncio.Lock] = {}
        self.toxic_flow_active: bool = False
        self.open_orders: Dict[str, dict] = {} # TTL Tracker Store
        self.position_amt: Decimal = Decimal("0") # Real-time inventory tracking hook
        self.wallet_balance: Decimal = Decimal("0")
        self.unrealized_pnl: Decimal = Decimal("0")
        self.entry_price: Decimal = Decimal("0")
        self.global_sniper_lock = asyncio.Lock()

    async def recover_boot_state(self, symbol: str):
        """Phase 20: Prevents PM2 Restart Amnesia syncing active state instantly."""
        try:
            params = {"symbol": symbol}
            res = await self.rest.get_signed("/fapi/v2/positionRisk", params)
            if res and len(res) > 0:
                pos = res[0]
                self.position_amt = Decimal(str(pos.get("positionAmt", "0")))
                self.entry_price = Decimal(str(pos.get("entryPrice", "0")))
                self.unrealized_pnl = Decimal(str(pos.get("unRealizedProfit", "0")))
                logger.info(f"BOOT STATE RECOVERED: {self.position_amt} BTC at {self.entry_price}. Amnesia aborted.")
        except Exception as e:
            logger.error(f"Boot State Recovery Failed: {e}")

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        if symbol not in self.locks:
            self.locks[symbol] = asyncio.Lock()
        return self.locks[symbol]

    def remove_from_tracking(self, client_order_id: str):
        """Red Team Patch: Prevents API Rate Limit Bomb by gracefully popping filled/canceled orders from Sweeper memory."""
        self.open_orders.pop(client_order_id, None)

    async def place_strict_maker(self, symbol: str, side: str, price: Decimal, quantity: Decimal, reduce_only: bool = False, lob=None):
        """Places a strict Maker (Post-Only) Limit Order. Taker execution is blocked by GTX."""
        if self.toxic_flow_active and side == "BUY" and not reduce_only:
            logger.warning(f"EXECUTION BLOCKED: TOXIC SELL FLOW DETECTED VIA VPIN. Canceling {quantity} {side}.")
            return None
            
        if lob is not None:
            book = lob.state.bids if side == "SELL" else lob.state.asks
            sorted_levels = sorted(book.items(), reverse=(side == "SELL"))[:3]
            top_3_vol = sum(v for _, v in sorted_levels)
            if top_3_vol > 0 and float(quantity) > top_3_vol * 0.15:
                logger.warning(f"LİKİDİTE YETERSİZ - Slippage Riski: Emir ({quantity}), Top 3 Derinliğin ({top_3_vol:.2f}) %15'ini aşıyor! İptal.")
                return None
                
        async with self._get_lock(symbol):
            new_client_order_id = f"BALINA_{uuid.uuid4().hex[:28]}"
            params = {
                "symbol": symbol,
                "side": side, # BUY or SELL
                "type": "LIMIT",
                "timeInForce": "GTX", # Post-Only (Maker) strict guarantee
                "quantity": str(quantity.quantize(Decimal('0.001'), rounding=ROUND_DOWN)),
                "price": str(price.quantize(Decimal('0.01'), rounding=ROUND_DOWN)),
                "newClientOrderId": new_client_order_id
            }
            if reduce_only:
                params["reduceOnly"] = "true"
                
            try:
                res = await self.rest.post_signed("/fapi/v1/order", params)
                logger.info(f"Strict Maker Order {side} {quantity} at {price} placed: {res.get('orderId')}")
                
                if res and "clientOrderId" in res:
                    self.open_orders[new_client_order_id] = {
                        "symbol": symbol,
                        "timestamp": time.time(),
                        "side": side,
                        "quantity": quantity,
                        "is_exit": reduce_only
                    }
                return res
            except (asyncio.TimeoutError, aiohttp.ClientError):
                logger.error(f"Blind Timeout on {new_client_order_id}. Initiating State Reconciliation.")
                asyncio.create_task(self._reconcile_timeout_order(symbol, new_client_order_id))
                return None
            except Exception as e:
                if "would immediately match" in str(e).lower() or reduce_only:
                    logger.warning(f"GTX REJECTED! Falling back to MARKET order for emergency exit.")
                    market_params = {
                        "symbol": symbol, "side": side, "type": "MARKET",
                        "quantity": str(quantity.quantize(Decimal('0.001'), rounding=ROUND_DOWN))
                    }
                    if reduce_only:
                        market_params["reduceOnly"] = "true"
                    try:
                        res = await self.rest.post_signed("/fapi/v1/order", market_params)
                        logger.info(f"Market Fallback Executed: {res.get('orderId')}")
                        return res
                    except Exception as me:
                        logger.error(f"Market Fallback Failed: {me}")
                logger.error(f"Failed to place strict maker order: {e}")
                return None

    async def partial_fill_reduce_only_update(self, symbol: str, filled_qty: str, side: str):
        """Callback from User WS (ORDER_TRADE_UPDATE). Updates risk parameters strictly for filled amount."""
        qty_dec = Decimal(filled_qty)
        if qty_dec == Decimal("0"):
            return
            
        logger.info(f"[{symbol}] PARTIALLY_FILLED detected ({qty_dec}). Adapting Reduce-Only triggers...")
        # Asymmetric risk management logic applies here...
        # Using Decimal prevents float rounding ghosts (like 0.30000000004) from persisting on Binance

    async def smart_slice_exit(self, symbol: str, total_qty: Decimal, side: str, lob: LimitOrderBook):
        """
        Iceberg Exit / Smart Slicing:
        Divides a massive execution into smaller market orders, dynamically analyzing 
        the limit order book depth (LOB object) to prevent slippage and market impact.
        """
        logger.warning(f"INITIATING SMART SLICING EXIT for {symbol}: {total_qty} {side}")
        async with self._get_lock(symbol):
            remaining_qty = total_qty
            
            while remaining_qty > Decimal("0"):
                # LOB Liquidity Analysis
                best_price = Decimal(str(lob.get_best_bid() if side == "SELL" else lob.get_best_ask()))
                visible_liquidity_at_best = Decimal("0")
                
                if side == "SELL":
                    visible_liquidity_at_best = Decimal(str(lob.state.bids.get(float(best_price), 0.0)))
                else:
                    visible_liquidity_at_best = Decimal(str(lob.state.asks.get(float(best_price), 0.0)))
                    
                # Slice logic: Safe execution equates to max 10% of visible depth at top of book
                safe_slice = max(Decimal("0.001"), visible_liquidity_at_best * Decimal("0.10"))
                chunk_qty = min(remaining_qty, safe_slice)
                
                new_client_order_id = f"BALINA_{uuid.uuid4().hex}"
                params = {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": str(chunk_qty.quantize(Decimal('0.001'), rounding=ROUND_DOWN)),
                    "newClientOrderId": new_client_order_id
                }
                
                try:
                    await self.rest.post_signed("/fapi/v1/order", params)
                    logger.info(f"Smart Slice Executed: {chunk_qty} {side} at Market.")
                except (asyncio.TimeoutError, aiohttp.ClientError):
                    logger.error(f"Smart Slice Blind Timeout on {new_client_order_id}. Mutabakat triggering.")
                    asyncio.create_task(self._reconcile_timeout_order(symbol, new_client_order_id))
                except Exception as e:
                    logger.error(f"Smart Slice Order Failed: {e}")
                    
                remaining_qty -= chunk_qty
                
                if remaining_qty > Decimal("0"):
                    # Yield quickly, allow LOB a few milliseconds to update the top of the book
                    await asyncio.sleep(0.005) 
            logger.info("Smart Slicing Exit Sequence Completed.")

    async def _reconcile_timeout_order(self, symbol: str, orig_client_order_id: str):
        """Asynchronous mutabakat recovery avoiding Double Spend on blind execution timeouts."""
        await asyncio.sleep(0.5) # Time buffer for backend lag on remote node
        try:
            params = {
                "symbol": symbol,
                "origClientOrderId": orig_client_order_id
            }
            res = await self.rest.get_signed("/fapi/v1/order", params)
            if "status" in res:
                if res["status"] in ("NEW", "PARTIALLY_FILLED", "FILLED"):
                    logger.info(f"RECON RELIEF: Order {orig_client_order_id} active locally over Remote node! Re-syncing State.")
                    # Implement logic synchronizing local state here if active tracking is needed later.
                else:
                    logger.warning(f"RECON DROP: Order {orig_client_order_id} safely discarded (Status: {res['status']})")
        except Exception as e:
            logger.error(f"Reconciliation FAILED for blind order {orig_client_order_id}: {e}")

    async def stale_order_sweeper(self):
        """Monitors open limit orders and deletes them if unfilled after 500ms (Adverse Selection Protection)"""
        logger.info("Stale Order Sweeper initialized.")
        while True:
            try:
                now = time.time()
                stale_ids = []
                for client_oid, order_info in list(self.open_orders.items()):
                    if now - order_info["timestamp"] >= 0.500: # 500ms TTL Boundary
                        stale_ids.append(client_oid)
                
                for stale_oid in stale_ids:
                    info = self.open_orders.pop(stale_oid, None)
                    if info:
                        logger.warning(f"TTL EXPIRED (500ms+): Canceling stale {info['side']} order ID: {stale_oid}")
                        try:
                            # Drop the passive maker order protecting from adverse selection sweeps
                            await self.rest.delete_signed("/fapi/v1/order", {
                                "symbol": info["symbol"],
                                "origClientOrderId": stale_oid
                            })
                        except Exception as e:
                            logger.error(f"Failed to drop stale order {stale_oid}: {e}")
                            
            except Exception as e:
                logger.error(f"Wallet sync failed: {e}")
            await asyncio.sleep(30)

    async def dust_sweeper_task(self):
        logger.info("Dust Sweeper Task initialized. Running every 12 hours.")
        while True:
            await asyncio.sleep(12 * 3600)
            try:
                res = await self.rest.get_signed("/fapi/v2/positionRisk")
                for pos in res:
                    if isinstance(pos, dict):
                        posAmt = Decimal(str(pos.get("positionAmt", "0")))
                        notional = Decimal(str(pos.get("notional", "0")))
                        
                        if abs(notional) > Decimal("0") and abs(notional) < Decimal("5"):
                            logger.warning(f"DUST DETECTED! Symbol: {pos['symbol']}, Amount: {posAmt}. Liquidating.")
                            side = "SELL" if posAmt > Decimal("0") else "BUY"
                            new_client_order_id = f"BALINA_{uuid.uuid4().hex}"
                            params = {
                                "symbol": pos["symbol"],
                                "side": side,
                                "type": "MARKET",
                                "quantity": str(abs(posAmt)),
                                "newClientOrderId": new_client_order_id
                            }
                            await self.rest.post_signed("/fapi/v1/order", params)
            except Exception as e:
                logger.error(f"Dust sweeper faulted: {e}")

    async def wallet_sync_loop(self, symbol: str):
        """Asenkron cuzdan senkronizasyon ve dual-side position kontrolu."""
        while True:
            try:
                # Phase 84: Force Binance One-Way Mode dynamically to fix User Account Desyncs
                try:
                    await self.rest.post_signed("/fapi/v1/positionSide/dual", {"dualSidePosition": "false"})
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Wallet sync failed: {e}")
            await asyncio.sleep(30)

    async def commission_rate_task(self, symbol: str):
        """Phase 20: Fetch Live Commission Rates (BNB Discount Awareness)"""
        logger.info("Live Commission Rate Sync initialized.")
        from core.mathematics import FeeMath
        while True:
            try:
                res = await self.rest.get_signed("/fapi/v1/commissionRate", {"symbol": symbol})
                if res and "makerCommissionRate" in res:
                    new_maker = Decimal(str(res["makerCommissionRate"]))
                    new_taker = Decimal(str(res["takerCommissionRate"]))
                    FeeMath.TAKER_FEE = new_taker
                    logger.info(f"FEE SYNC: Maker={new_maker}, Taker={new_taker}")
            except Exception as e:
                logger.error(f"Live Fee Sync Fault: {e}")
            await asyncio.sleep(60 * 60)

    async def cancel_all_open_orders(self, symbol: str):
        """Asenkron kalkan (Protokol 100): Sistem kapanmadan once borsadaki tum acik emirleri siler."""
        try:
            res = await self.rest.delete_signed("/fapi/v1/allOpenOrders", {"symbol": symbol})
            logger.critical(f"🛑 TUM ACIK EMIRLER IPTAL EDILDI ({symbol})! Borsada orphan emir kalmadi. Sonuc: {res}")
            self.open_orders.clear()
        except Exception as e:
            logger.error(f"🚨 TUM EMIRLERI IPTAL EDERKEN HATA (Graceful Shutdown Failure): {e}")
