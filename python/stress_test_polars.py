import asyncio
import os
import time

import polars as pl

from seahorse_ai.tools.polars_analyst import (
    polars_inspect_join,
    polars_profile,
    polars_query,
)

async def stress_test():
    print("🚀 Starting High-Performance Polars Stress Test...")
    
    # 1. Generate Large Data (1 Million rows)
    num_rows = 1_000_000
    print(f"📊 Generating {num_rows:,} rows of data...")
    
    orders = pl.DataFrame({
        "order_id": range(num_rows),
        "customer_id": [i % 100_000 for i in range(num_rows)],
        "amount": [round(i * 0.5, 2) for i in range(num_rows)],
        "category_id": [i % 50 for i in range(num_rows)]
    })
    
    customers = pl.DataFrame({
        "customer_id": range(100_000),
        "name": [f"Customer_{i}" for i in range(100_000)],
        "region": [["North", "South", "East", "West"][i % 4] for i in range(100_000)]
    })
    
    orders_path = "/tmp/stress_orders.parquet"
    customers_path = "/tmp/stress_customers.parquet"
    
    orders.write_parquet(orders_path)
    customers.write_parquet(customers_path)
    
    # 2. Test polars_profile
    print("\n🔍 Testing polars_profile on large data...")
    start = time.time()
    profile_res = await polars_profile([orders_path, customers_path])
    end = time.time()
    print(f"✅ Profile completed in {end - start:.4f}s")
    # print(profile_res) # Too long to print all
    
    # 3. Test polars_inspect_join
    print("\n🤝 Testing polars_inspect_join...")
    start = time.time()
    join_info = await polars_inspect_join(orders_path, customers_path)
    end = time.time()
    print(f"✅ Inspect Join completed in {end - start:.4f}s")
    print(join_info)
    
    # 4. Stress Test Complex Join + Aggregation
    print("\n⚡ Testing Complex Join + Aggregation (1M rows)...")
    expression = "t0.join(t1, on='customer_id').group_by('region').agg(pl.col('amount').sum().alias('total_sales')).sort('total_sales', descending=True)"
    
    start = time.time()
    query_res = await polars_query([orders_path, customers_path], expression=expression)
    end = time.time()
    
    print(f"✅ Query completed in {end - start:.4f}s")
    print(query_res)

    # Cleanup
    os.remove(orders_path)
    os.remove(customers_path)
    print("\n✅ Stress test finished successfully!")

if __name__ == "__main__":
    asyncio.run(stress_test())
