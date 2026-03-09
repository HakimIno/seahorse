"""seahorse_ai.analysis.feeder — Real-time sales simulator for Seahorse."""
import asyncio
import random
import logging
import os
from datetime import datetime
import asyncpg

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] FEEDS: %(message)s')
logger = logging.getLogger(__name__)

# Load from environment
PG_URI = os.environ.get("SEAHORSE_PG_URI")

class RealTimeFeeder:
    def __init__(self):
        self.conn = None
        self.branches = []
        self.products = []
        self.customers = []
        
        # Anomaly simulation state
        self.anomaly_branch_id = 1 # Silom Complex (Default test)
        self.anomaly_end_time = 0

    async def _init_db(self):
        """Initialize connection and load reference data."""
        if not PG_URI:
            logger.error("Feeder: SEAHORSE_PG_URI not set. Exit.")
            return False

        try:
            self.conn = await asyncpg.connect(PG_URI)
            
            # Load branches
            rows = await self.conn.fetch("SELECT id, name FROM branches;")
            self.branches = [dict(r) for r in rows]
            
            # Load products
            rows = await self.conn.fetch("SELECT id, name, base_price FROM products;")
            self.products = [dict(r) for r in rows]
            
            # Load customers
            rows = await self.conn.fetch("SELECT id FROM customers LIMIT 1000;")
            self.customers = [r['id'] for r in rows]
            
            logger.info("Feeder: Reference data loaded (%d branches, %d products)", len(self.branches), len(self.products))
            return True
        except Exception as e:
            logger.error("Feeder DB Init Error: %s", e)
            return False

    def trigger_anomaly(self, duration_sec=1800):
        """Pick a random branch to stop selling for a while."""
        if not self.branches:
            return
        branch = random.choice(self.branches)
        self.anomaly_branch_id = branch['id']
        self.anomaly_end_time = asyncio.get_event_loop().time() + duration_sec
        logger.warning("🚨 SIMULATING ANOMALY: Branch '%s' (ID: %s) has stopped selling for %ds!", branch['name'], branch['id'], duration_sec)

    async def run(self):
        if not await self._init_db():
            return

        logger.info("Real-time feeder started. Inserting 1-4 transactions every 15-30s.")
        
        # Initial anomaly for testing context
        logger.warning("🚨 TEST MODE: Forcing initial anomaly for branch ID 1 (Silom Complex)")
        self.anomaly_end_time = asyncio.get_event_loop().time() + 1800

        while True:
            try:
                # 1. Decide how many sales in this tick
                num_sales = random.randint(1, 4)
                
                current_loop_time = asyncio.get_event_loop().time()

                for _ in range(num_sales):
                    branch = random.choice(self.branches)
                    
                    # Skip if this branch is currently in an anomaly
                    if self.anomaly_branch_id == branch['id'] and current_loop_time < self.anomaly_end_time:
                        continue
                    elif self.anomaly_branch_id == branch['id'] and current_loop_time >= self.anomaly_end_time:
                        logger.info("✅ Anomaly ended for branch ID: %s", branch['id'])
                        self.anomaly_branch_id = None

                    product = random.choice(self.products)
                    customer_id = random.choice(self.customers)
                    qty = random.randint(1, 3)
                    total = float(product['base_price']) * qty
                    
                    await self.conn.execute(
                        "INSERT INTO transactions (branch_id, product_id, customer_id, quantity, total_amount, transaction_date) "
                        "VALUES ($1, $2, $3, $4, $5, $6)",
                        branch['id'], product['id'], customer_id, qty, total, datetime.now()
                    )
                    logger.info("🛒 Sale: %s แก้ว (%s) @ %s", qty, product['name'], branch['name'])
                
                # Proactive anomaly trigger (2% chance)
                if random.random() < 0.02:
                    self.trigger_anomaly()

                wait_time = random.uniform(15, 30)
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error("Feeder loop error: %s", e)
                # Attempt to reconnect if lost
                await asyncio.sleep(10)
                try:
                    await self._init_db()
                except:
                    pass

async def main():
    feeder = RealTimeFeeder()
    await feeder.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Feeder stopped.")
