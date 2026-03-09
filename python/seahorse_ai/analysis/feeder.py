"""seahorse_ai.analysis.feeder — Real-time sales simulator for Seahorse."""
import time
import random
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] FEEDS: %(message)s')
logger = logging.getLogger(__name__)

PG_URI = "postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise"

class RealTimeFeeder:
    def __init__(self):
        self.conn = psycopg2.connect(PG_URI)
        self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        self.branches = self._load_branches()
        self.products = self._load_products()
        self.customers = self._load_customers()
        # Force anomaly for testing
        self.anomaly_branch_id = 1 # Silom Complex
        self.anomaly_end_time = time.time() + 1800 # 30 mins
        logger.warning("🚨 TEST MODE: Forcing anomaly for branch ID 1")

    def _load_branches(self):
        self.cursor.execute("SELECT id, name FROM branches;")
        return self.cursor.fetchall()

    def _load_products(self):
        self.cursor.execute("SELECT id, name, base_price FROM products;")
        return self.cursor.fetchall()

    def _load_customers(self):
        self.cursor.execute("SELECT id FROM customers LIMIT 1000;")
        return [r['id'] for r in self.cursor.fetchall()]

    def trigger_anomaly(self, duration_sec=300):
        """Pick a random branch to stop selling for a while."""
        branch = random.choice(self.branches)
        self.anomaly_branch_id = branch['id']
        self.anomaly_end_time = time.time() + duration_sec
        logger.warning("🚨 SIMULATING ANOMALY: Branch '%s' (ID: %s) has stopped selling!", branch['name'], branch['id'])

    def run(self):
        logger.info("Real-time feeder started. Inserting 1-3 transactions every 15-30s.")
        while True:
            try:
                # 1. Decide how many sales in this tick
                num_sales = random.randint(1, 4)
                
                for _ in range(num_sales):
                    branch = random.choice(self.branches)
                    
                    # Skip if this branch is currently in an anomaly (e.g. machine broken)
                    if self.anomaly_branch_id == branch['id'] and time.time() < self.anomaly_end_time:
                        continue
                    elif self.anomaly_branch_id == branch['id'] and time.time() >= self.anomaly_end_time:
                        logger.info("✅ Anomaly ended for branch ID: %s", branch['id'])
                        self.anomaly_branch_id = None

                    product = random.choice(self.products)
                    customer_id = random.choice(self.customers)
                    qty = random.randint(1, 3)
                    total = float(product['base_price']) * qty
                    
                    self.cursor.execute(
                        "INSERT INTO transactions (branch_id, product_id, customer_id, quantity, total_amount, transaction_date) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (branch['id'], product['id'], customer_id, qty, total, datetime.now())
                    )
                    logger.info("🛒 Sale: %s แก้ว (%s) @ %s", qty, product['name'], branch['name'])
                
                self.conn.commit()
                
                # Randomly trigger an anomaly every ~10 minutes (probabilistically)
                if random.random() < 0.02: # 2% chance per check
                    self.trigger_anomaly()

                wait_time = random.uniform(15, 30)
                time.sleep(wait_time)

            except Exception as e:
                logger.error("Feeder error: %s", e)
                self.conn.rollback()
                time.sleep(10)

if __name__ == "__main__":
    feeder = RealTimeFeeder()
    feeder.run()
