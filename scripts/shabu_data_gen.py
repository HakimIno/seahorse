import asyncio
import os
import random
from datetime import date, datetime, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv(".env")

PG_URI = os.getenv(
    "SEAHORSE_PG_URI",
    "postgresql://seahorse_user:seahorse_password@localhost:5432/seahorse_enterprise",
)

START_DATE = datetime(2024, 10, 1)
END_DATE = datetime(2025, 3, 31)

# ---------------------------------------------------------------------------
# 25 สาขาไม่ซ้ำกัน — ชื่อ + เมือง + ย่าน unique ทุกแถว
# ---------------------------------------------------------------------------
BRANCHES_FIXED = [
    # Bangkok (12 สาขา)
    {
        "name": "ตี๋น้อย สยามพารากอน",
        "city": "Bangkok",
        "district": "Siam Paragon",
        "region": "Central",
        "type": "Mall",
        "sqm": 420,
    },
    {
        "name": "ตี๋น้อย เซ็นทรัลเวิลด์",
        "city": "Bangkok",
        "district": "Central World",
        "region": "Central",
        "type": "Mall",
        "sqm": 380,
    },
    {
        "name": "ตี๋น้อย เอ็มควอเทียร์",
        "city": "Bangkok",
        "district": "EmQuartier",
        "region": "Central",
        "type": "Mall",
        "sqm": 360,
    },
    {
        "name": "ตี๋น้อย อารีย์",
        "city": "Bangkok",
        "district": "Ari",
        "region": "Central",
        "type": "Standalone",
        "sqm": 210,
    },
    {
        "name": "ตี๋น้อย สุขุมวิท 11",
        "city": "Bangkok",
        "district": "Sukhumvit",
        "region": "Central",
        "type": "Standalone",
        "sqm": 240,
    },
    {
        "name": "ตี๋น้อย บางนา",
        "city": "Bangkok",
        "district": "Bang Na",
        "region": "Central",
        "type": "Mall",
        "sqm": 300,
    },
    {
        "name": "ตี๋น้อย จตุจักร",
        "city": "Bangkok",
        "district": "Chatuchak",
        "region": "Central",
        "type": "Standalone",
        "sqm": 180,
    },
    {
        "name": "ตี๋น้อย ห้วยขวาง",
        "city": "Bangkok",
        "district": "Huai Khwang",
        "region": "Central",
        "type": "Standalone",
        "sqm": 200,
    },
    {
        "name": "ตี๋น้อย ลาดพร้าว",
        "city": "Bangkok",
        "district": "Lat Phrao",
        "region": "Central",
        "type": "Mall",
        "sqm": 320,
    },
    {
        "name": "ตี๋น้อย พระราม 9",
        "city": "Bangkok",
        "district": "Rama 9",
        "region": "Central",
        "type": "Mall",
        "sqm": 350,
    },
    {
        "name": "ตี๋น้อย ออนนุช",
        "city": "Bangkok",
        "district": "On Nut",
        "region": "Central",
        "type": "Standalone",
        "sqm": 195,
    },
    {
        "name": "ตี๋น้อย ดอนเมือง",
        "city": "Bangkok",
        "district": "Don Mueang",
        "region": "Central",
        "type": "Standalone",
        "sqm": 175,
    },
    # Chiang Mai (3 สาขา)
    {
        "name": "ตี๋น้อย มายา เชียงใหม่",
        "city": "Chiang Mai",
        "district": "Maya",
        "region": "North",
        "type": "Mall",
        "sqm": 290,
    },
    {
        "name": "ตี๋น้อย นิมมานฯ",
        "city": "Chiang Mai",
        "district": "Nimman",
        "region": "North",
        "type": "Standalone",
        "sqm": 185,
    },
    {
        "name": "ตี๋น้อย เซ็นทรัล เชียงใหม่",
        "city": "Chiang Mai",
        "district": "Central Festival",
        "region": "North",
        "type": "Mall",
        "sqm": 260,
    },
    # Chonburi (2 สาขา)
    {
        "name": "ตี๋น้อย พัทยา",
        "city": "Chonburi",
        "district": "Central Pattaya",
        "region": "East",
        "type": "Mall",
        "sqm": 270,
    },
    {
        "name": "ตี๋น้อย ศรีราชา",
        "city": "Chonburi",
        "district": "Si Racha",
        "region": "East",
        "type": "Standalone",
        "sqm": 160,
    },
    # Phuket (3 สาขา)
    {
        "name": "ตี๋น้อย ป่าตอง",
        "city": "Phuket",
        "district": "Patong",
        "region": "South",
        "type": "Standalone",
        "sqm": 220,
    },
    {
        "name": "ตี๋น้อย เมืองเก่าภูเก็ต",
        "city": "Phuket",
        "district": "Old Town",
        "region": "South",
        "type": "Standalone",
        "sqm": 170,
    },
    {
        "name": "ตี๋น้อย เซ็นทรัล ภูเก็ต",
        "city": "Phuket",
        "district": "Central Phuket",
        "region": "South",
        "type": "Mall",
        "sqm": 310,
    },
    # Khon Kaen (2 สาขา)
    {
        "name": "ตี๋น้อย เซ็นทรัล ขอนแก่น",
        "city": "Khon Kaen",
        "district": "Central Khon Kaen",
        "region": "Northeast",
        "type": "Mall",
        "sqm": 250,
    },
    {
        "name": "ตี๋น้อย เมืองขอนแก่น",
        "city": "Khon Kaen",
        "district": "Muang Khon Kaen",
        "region": "Northeast",
        "type": "Standalone",
        "sqm": 155,
    },
    # Nakhon Ratchasima (3 สาขา)
    {
        "name": "ตี๋น้อย เดอะมอลล์ โคราช",
        "city": "Nakhon Ratchasima",
        "district": "The Mall Korat",
        "region": "Northeast",
        "type": "Mall",
        "sqm": 280,
    },
    {
        "name": "ตี๋น้อย เทอร์มินอล21 โคราช",
        "city": "Nakhon Ratchasima",
        "district": "Terminal 21 Korat",
        "region": "Northeast",
        "type": "Mall",
        "sqm": 265,
    },
    {
        "name": "ตี๋น้อย เมืองโคราช",
        "city": "Nakhon Ratchasima",
        "district": "Muang Korat",
        "region": "Northeast",
        "type": "Standalone",
        "sqm": 150,
    },
]

assert len(BRANCHES_FIXED) == 25, f"Expected 25 branches, got {len(BRANCHES_FIXED)}"

# ---------------------------------------------------------------------------
CITY_DEMAND = {
    "Bangkok": 1.0,
    "Chonburi": 0.75,
    "Phuket": 0.85,
    "Chiang Mai": 0.65,
    "Khon Kaen": 0.50,
    "Nakhon Ratchasima": 0.45,
}
BRANCH_TYPE_LIFT = {"Mall": 1.20, "Standalone": 0.85}

# ---------------------------------------------------------------------------
# Wages and Rent Calibration (2024-2025 Thailand Rates)
# ---------------------------------------------------------------------------
WAGE_BASE = {
    "Bangkok": 16500,
    "Phuket": 16500,
    "Chonburi": 14500,
    "Chiang Mai": 14000,
    "Khon Kaen": 13500,
    "Nakhon Ratchasima": 13500,
}
RENT_SQM_RATE = {
    "Bangkok": {"Mall": 1200, "Standalone": 800},
    "Others": {"Mall": 600, "Standalone": 400},
}
# ---------------------------------------------------------------------------

TH_HOLIDAYS = {
    # 2024
    date(2024, 1, 1),  # New Year
    date(2024, 2, 24),  # Makha Bucha
    date(2024, 4, 6),  # Chakri Day
    date(2024, 4, 12),  # Songkran
    date(2024, 4, 13),  # Songkran
    date(2024, 4, 14),  # Songkran
    date(2024, 4, 15),  # Songkran
    date(2024, 5, 1),  # Labour Day
    date(2024, 5, 4),  # Coronation Day
    date(2024, 5, 22),  # Visakha Bucha
    date(2024, 7, 20),  # Asanha Bucha
    date(2024, 7, 28),  # King's Birthday
    date(2024, 8, 12),  # Queen Mother's Birthday
    date(2024, 10, 13),  # Passing of Rama IX
    date(2024, 10, 23),  # Chulalongkorn Day
    date(2024, 12, 5),  # King Rama IX Birthday
    date(2024, 12, 10),  # Constitution Day
    date(2024, 12, 31),  # New Year's Eve
    # 2025
    date(2025, 1, 1),
    date(2025, 2, 12),  # Makha Bucha
    date(2025, 4, 6),
    date(2025, 4, 13),
    date(2025, 4, 14),
    date(2025, 4, 15),
}

# ---------------------------------------------------------------------------
MENU_ITEMS = [
    {"name": "Wagyu Beef Set", "category": "Meat", "price": 899, "cost": 450, "pop": 6},
    {"name": "Pork Belly Set", "category": "Meat", "price": 459, "cost": 180, "pop": 20},
    {"name": "Australian Striploin", "category": "Meat", "price": 699, "cost": 320, "pop": 10},
    {"name": "Mixed Pork & Chicken", "category": "Meat", "price": 359, "cost": 130, "pop": 18},
    {"name": "Premium Seafood Bowl", "category": "Seafood", "price": 799, "cost": 400, "pop": 8},
    {"name": "Shrimp & Squid Set", "category": "Seafood", "price": 499, "cost": 220, "pop": 12},
    {"name": "Mixed Vegetable Basket", "category": "Veggie", "price": 129, "cost": 30, "pop": 25},
    {"name": "Mushroom Platter", "category": "Veggie", "price": 159, "cost": 40, "pop": 20},
    {"name": "Tofu & Egg Basket", "category": "Veggie", "price": 99, "cost": 20, "pop": 15},
    {"name": "Spicy Mala Soup", "category": "Soup", "price": 50, "cost": 10, "pop": 30},
    {"name": "Truffle Cream Soup", "category": "Soup", "price": 80, "cost": 20, "pop": 12},
    {"name": "Original Shabu Soup", "category": "Soup", "price": 0, "cost": 5, "pop": 40},
    {"name": "Tom Yum Soup", "category": "Soup", "price": 50, "cost": 12, "pop": 25},
    {"name": "Green Tea (Refill)", "category": "Drink", "price": 39, "cost": 5, "pop": 50},
    {"name": "Fruit Punch", "category": "Drink", "price": 65, "cost": 15, "pop": 30},
    {"name": "Soft Drink", "category": "Drink", "price": 45, "cost": 8, "pop": 35},
    {"name": "Fresh Juice", "category": "Drink", "price": 89, "cost": 25, "pop": 15},
    {"name": "Signature Dipping Sauce", "category": "Sauce", "price": 0, "cost": 10, "pop": 80},
    {"name": "Spicy Sauce Add-on", "category": "Sauce", "price": 20, "cost": 5, "pop": 40},
    {"name": "Ice Cream Sundae", "category": "Dessert", "price": 89, "cost": 25, "pop": 20},
    {"name": "Mochi Platter", "category": "Dessert", "price": 69, "cost": 18, "pop": 15},
]

HOUR_RANGE = list(range(10, 23))
HOUR_WEIGHTS = [1, 3, 12, 8, 4, 2, 2, 4, 14, 18, 12, 6, 2]

PAYMENT_METHODS = ["QR", "Credit Card", "Cash", "Mobile Banking"]
PAYMENT_WEIGHTS = [55, 20, 10, 15]

# ---------------------------------------------------------------------------


def get_day_multiplier(dt: datetime, city: str, b_type: str) -> float:
    d = dt.date()
    is_weekend = d.weekday() >= 5
    is_holiday = d in TH_HOLIDAYS
    weekend_lift = 1.80 if is_weekend else 1.0
    holiday_lift = 2.00 if is_holiday else 1.0
    return (
        weekend_lift
        * holiday_lift
        * CITY_DEMAND[city]
        * BRANCH_TYPE_LIFT[b_type]
        * random.uniform(0.90, 1.10)
    )


def base_orders(sqm: int) -> int:
    return int((sqm // 6) * 2.2)


def build_order(cust_count: int) -> list[dict]:
    cat = {
        c: [m for m in MENU_ITEMS if m["category"] == c]
        for c in ["Meat", "Seafood", "Soup", "Veggie", "Drink", "Sauce", "Dessert"]
    }
    cp = {c: [m["pop"] for m in cat[c]] for c in cat}

    meat_pool = cat["Meat"] + cat["Seafood"]
    meat_pop = [m["pop"] for m in meat_pool]

    items = []
    for _ in range(cust_count):
        items.append({**random.choices(meat_pool, weights=meat_pop)[0], "qty": 1})

    num_broths = 1 if cust_count <= 2 else 2
    for _ in range(num_broths):
        items.append({**random.choices(cat["Soup"], weights=cp["Soup"])[0], "qty": 1})

    for _ in range(random.randint(1, min(3, cust_count + 1))):
        items.append({**random.choices(cat["Veggie"], weights=cp["Veggie"])[0], "qty": 1})

    for _ in range(cust_count):
        items.append({**random.choices(cat["Drink"], weights=cp["Drink"])[0], "qty": 1})

    for sauce in cat["Sauce"]:
        items.append({**sauce, "qty": 1})

    if random.random() < 0.60:
        items.append(
            {
                **random.choices(cat["Dessert"], weights=cp["Dessert"])[0],
                "qty": random.randint(1, cust_count),
            }
        )
    return items


# ---------------------------------------------------------------------------


async def setup_db(conn):
    print("Dropping & recreating tables...")
    for t in ["inventory_logs", "branch_inventory", "expenses", "sales_details", "sales", "menu", "branches"]:
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    await conn.execute("""
        CREATE TABLE branches (
            id           SERIAL PRIMARY KEY,
            name         TEXT    NOT NULL UNIQUE,
            city         TEXT    NOT NULL,
            district     TEXT    NOT NULL,
            region       TEXT    NOT NULL,
            branch_type  TEXT    NOT NULL,
            sq_meters    INTEGER,
            num_tables   INTEGER,
            opening_date DATE,
            UNIQUE (city, district)
        )
    """)
    await conn.execute("""
        CREATE TABLE menu (
            id       SERIAL PRIMARY KEY,
            name     TEXT          NOT NULL UNIQUE,
            category TEXT          NOT NULL,
            price    DECIMAL(10,2),
            cost     DECIMAL(10,2)
        )
    """)
    await conn.execute("""
        CREATE TABLE sales (
            id              SERIAL PRIMARY KEY,
            branch_id       INTEGER REFERENCES branches(id),
            timestamp       TIMESTAMP NOT NULL,
            customer_count  INTEGER,
            table_number    INTEGER,
            duration_mins   INTEGER,
            total_amount    DECIMAL(12,2),
            discount_amount DECIMAL(10,2) DEFAULT 0,
            payment_method  TEXT,
            is_holiday      BOOLEAN DEFAULT FALSE
        )
    """)
    await conn.execute("""
        CREATE TABLE sales_details (
            id           SERIAL PRIMARY KEY,
            sale_id      INTEGER REFERENCES sales(id),
            menu_item_id INTEGER REFERENCES menu(id),
            quantity     INTEGER,
            unit_price   DECIMAL(10,2),
            subtotal     DECIMAL(12,2)
        )
    """)
    await conn.execute("""
        CREATE TABLE branch_inventory (
            id             SERIAL PRIMARY KEY,
            branch_id      INTEGER REFERENCES branches(id),
            menu_item_id   INTEGER REFERENCES menu(id),
            stock_quantity INTEGER NOT NULL DEFAULT 0,
            last_updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (branch_id, menu_item_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE inventory_logs (
            id           SERIAL PRIMARY KEY,
            branch_id    INTEGER REFERENCES branches(id),
            menu_item_id INTEGER REFERENCES menu(id),
            change_qty   INTEGER NOT NULL,
            reason       TEXT NOT NULL, -- 'SALE', 'RESTOCK', 'WASTE'
            timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE TABLE expenses (
            id          SERIAL PRIMARY KEY,
            branch_id   INTEGER REFERENCES branches(id),
            category    TEXT NOT NULL, -- 'RENT', 'SALARY', 'UTILITIES', 'MARKETING', 'PO'
            amount      DECIMAL(12,2) NOT NULL,
            expense_date DATE NOT NULL,
            description TEXT
        )
    """)


async def generate_data():
    try:
        conn = await asyncpg.connect(PG_URI)
    except Exception as e:
        print(f"DB connection error: {e}")
        return

    await setup_db(conn)

    # --- Branches ---
    print("Inserting 25 unique branches...")
    branch_meta = []
    for b in BRANCHES_FIXED:
        open_date = (START_DATE - timedelta(days=random.randint(60, 1200))).date()
        num_tables = b["sqm"] // 6
        b_id = await conn.fetchval(
            """
            INSERT INTO branches (name, city, district, region, branch_type, sq_meters, num_tables, opening_date)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
        """,
            b["name"],
            b["city"],
            b["district"],
            b["region"],
            b["type"],
            b["sqm"],
            num_tables,
            open_date,
        )
        branch_meta.append({**b, "id": b_id, "tables": num_tables})
    print(f"  {len(branch_meta)} branches inserted.")

    # --- Menu ---
    print("Inserting menu...")
    menu_id_map = {}
    menu_cost_map = {}
    for item in MENU_ITEMS:
        m_id = await conn.fetchval(
            """
            INSERT INTO menu (name, category, price, cost)
            VALUES ($1,$2,$3,$4) RETURNING id
        """,
            item["name"],
            item["category"],
            item["price"],
            item["cost"],
        )
        menu_id_map[item["name"]] = m_id
        menu_cost_map[m_id] = float(item["cost"])

    # --- Initialize Inventory ---
    print("Initializing inventory for each branch...")
    inventory_state = {}  # (branch_id, menu_item_id) -> quantity
    init_inv_rows = []
    for b in branch_meta:
        for m_name, m_id in menu_id_map.items():
            qty = random.randint(300, 700)
            inventory_state[(b["id"], m_id)] = qty
            init_inv_rows.append((b["id"], m_id, qty))

    await conn.executemany(
        "INSERT INTO branch_inventory (branch_id, menu_item_id, stock_quantity) VALUES ($1, $2, $3)",
        init_inv_rows,
    )

    # --- Sales & Expenses ---
    print("Generating sales and expenses...")
    current_date = START_DATE
    branch_monthly_revenue = {b["id"]: 0.0 for b in branch_meta}

    while current_date <= END_DATE:
        day_rows = []
        day_details = []
        inv_logs = []
        daily_expenses = []

        is_first_of_month = current_date.day == 1
        is_monday = current_date.weekday() == 0
        is_last_of_month = (current_date + timedelta(days=1)).month != current_date.month

        for branch in branch_meta:
            # 1. Monthly Fixed Costs (Rent & Salary)
            if is_first_of_month:
                # Rent
                city_key = "Bangkok" if branch["city"] == "Bangkok" else "Others"
                rent_rate = RENT_SQM_RATE[city_key][branch["type"]]
                rent_amount = branch["sqm"] * rent_rate
                daily_expenses.append(
                    (branch["id"], "RENT", rent_amount, current_date.date(), f"Monthly Rent - {branch['sqm']} sqm")
                )

                # Salary (1 staff per 4 tables)
                staff_count = max(4, branch["tables"] // 4)
                wage_base = WAGE_BASE.get(branch["city"], 13500)
                salary_amount = staff_count * (wage_base + 750)  # Base + Social Security
                daily_expenses.append(
                    (branch["id"], "SALARY", salary_amount, current_date.date(), f"Staff Salary - {staff_count} heads")
                )

            # 2. Weekly Restock (PO)
            if is_monday:
                po_total = 0.0
                for m_name, m_id in menu_id_map.items():
                    current_stock = inventory_state[(branch["id"], m_id)]
                    if current_stock < 150:
                        restock_qty = 500 - current_stock
                        inventory_state[(branch["id"], m_id)] += restock_qty
                        po_total += restock_qty * menu_cost_map[m_id]
                        inv_logs.append((branch["id"], m_id, restock_qty, "RESTOCK", current_date))
                
                if po_total > 0:
                    daily_expenses.append(
                        (branch["id"], "PO", po_total, current_date.date(), "Weekly Raw Material Procurement")
                    )

            # 3. Daily Sales
            mult = get_day_multiplier(current_date, branch["city"], branch["type"])
            n_orders = max(1, int(base_orders(branch["sqm"]) * mult * random.uniform(0.8, 1.2)))
            is_hol = current_date.date() in TH_HOLIDAYS

            for _ in range(n_orders):
                hour = random.choices(HOUR_RANGE, weights=HOUR_WEIGHTS)[0]
                ts = current_date.replace(hour=hour, minute=random.randint(0, 59))
                cc = random.choices([1, 2, 3, 4, 5, 6], weights=[5, 25, 25, 25, 12, 8])[0]
                dur = max(30, min(120, int(random.gauss(65 + cc * 5, 15))))
                tbl = random.randint(1, branch["tables"])
                payment = random.choices(PAYMENT_METHODS, weights=PAYMENT_WEIGHTS)[0]
                ordered = build_order(cc)

                raw = sum(it["price"] * it["qty"] for it in ordered)
                discount = (
                    round(raw * random.choice([10, 15, 20]) / 100, 2)
                    if random.random() < 0.15
                    else 0.0
                )
                total = max(0.0, raw - discount)
                branch_monthly_revenue[branch["id"]] += total

                day_rows.append((branch["id"], ts, cc, tbl, dur, total, discount, payment, is_hol))
                day_details.append(ordered)

                # Deduct Inventory
                for it in ordered:
                    m_id = menu_id_map[it["name"]]
                    qty = it["qty"]
                    inventory_state[(branch["id"], m_id)] -= qty
                    inv_logs.append((branch["id"], m_id, -qty, "SALE", ts))

            # 4. Monthly Variable Costs (Utilities & Marketing)
            if is_last_of_month:
                rev = branch_monthly_revenue[branch["id"]]
                # Utilities (Base + 3% Rev)
                util_amount = (branch["sqm"] * 50) + (rev * 0.03)
                daily_expenses.append(
                    (branch["id"], "UTILITIES", util_amount, current_date.date(), "Monthly Electricity & Water")
                )
                # Marketing (2-5% Rev)
                mkt_amount = rev * random.uniform(0.02, 0.05)
                daily_expenses.append(
                    (branch["id"], "MARKETING", mkt_amount, current_date.date(), "Monthly Marketing & Promotion")
                )
                # Reset for next month
                branch_monthly_revenue[branch["id"]] = 0.0

        # --- Bulk Inserts for the day ---
        
        # Expenses
        if daily_expenses:
            await conn.executemany(
                "INSERT INTO expenses (branch_id, category, amount, expense_date, description) VALUES ($1, $2, $3, $4, $5)",
                daily_expenses
            )

        # Sales
        if day_rows:
            sale_ids = await conn.fetch(
                """
                INSERT INTO sales
                    (branch_id,timestamp,customer_count,table_number,
                     duration_mins,total_amount,discount_amount,payment_method,is_holiday)
                SELECT b,ts,cc,tn,dm,ta,da,pm,ih
                FROM UNNEST($1::int[],$2::timestamp[],$3::int[],$4::int[],
                            $5::int[],$6::float[],$7::float[],$8::text[],$9::bool[])
                     AS t(b,ts,cc,tn,dm,ta,da,pm,ih)
                RETURNING id
            """,
                [r[0] for r in day_rows],
                [r[1] for r in day_rows],
                [r[2] for r in day_rows],
                [r[3] for r in day_rows],
                [r[4] for r in day_rows],
                [float(r[5]) for r in day_rows],
                [float(r[6]) for r in day_rows],
                [r[7] for r in day_rows],
                [r[8] for r in day_rows],
            )

            detail_rows = []
            for rec, ordered in zip(sale_ids, day_details, strict=True):
                for it in ordered:
                    qty = it["qty"]
                    price = float(it["price"])
                    detail_rows.append((rec["id"], menu_id_map[it["name"]], qty, price, price * qty))

            if detail_rows:
                await conn.executemany(
                    "INSERT INTO sales_details (sale_id,menu_item_id,quantity,unit_price,subtotal) VALUES ($1,$2,$3,$4,$5)",
                    detail_rows,
                )

        # Inventory Logs
        if inv_logs:
            await conn.executemany(
                "INSERT INTO inventory_logs (branch_id, menu_item_id, change_qty, reason, timestamp) VALUES ($1, $2, $3, $4, $5)",
                inv_logs
            )

        print(f"  {current_date.date()} — {len(day_rows):,} orders, {len(daily_expenses)} expenses")
        current_date += timedelta(days=1)

    # Final Sync Branch Inventory
    print("Syncing final inventory levels...")
    sync_rows = []
    for (b_id, m_id), qty in inventory_state.items():
        sync_rows.append((qty, b_id, m_id))
    
    await conn.executemany(
        "UPDATE branch_inventory SET stock_quantity = $1, last_updated = CURRENT_TIMESTAMP WHERE branch_id = $2 AND menu_item_id = $3",
        sync_rows
    )

    await conn.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(generate_data())
