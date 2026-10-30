"""Seeded demo catalog (spec section 2). Every listing is marked seeded_demo.

Amina is listed here until the chat flow (spec 3.1) can create her listing live.
"""

from pydantic import BaseModel


class Product(BaseModel):
    product_id: str
    seller_id: str
    seller_name: str
    title: str
    category: str
    variants: list[str]
    price_usd: float
    capacity_per_week: int
    ship_days: int
    ship_from_city: str
    data_source: str = "seeded_demo"


DEMO_PRODUCTS = [
    Product(
        product_id="p_amina_cushion",
        seller_id="s_amina",
        seller_name="Amina",
        title="Hand-embroidered cushion cover",
        category="home textiles",
        variants=["red", "teal", "mustard"],
        price_usd=18.00,
        capacity_per_week=4,
        ship_days=9,
        ship_from_city="Lahore",
    ),
    Product(
        product_id="p_priya_cushion",
        seller_id="s_priya",
        seller_name="Priya",
        title="Mirror-work embroidered cushion cover",
        category="home textiles",
        variants=["indigo", "saffron"],
        price_usd=16.00,
        capacity_per_week=4,
        ship_days=10,
        ship_from_city="Jaipur",
    ),
    Product(
        product_id="p_lucia_cushion",
        seller_id="s_lucia",
        seller_name="Lucía",
        title="Oaxacan embroidered cushion cover",
        category="home textiles",
        variants=["white", "black"],
        price_usd=22.00,
        capacity_per_week=3,
        ship_days=6,
        ship_from_city="Oaxaca",
    ),
    Product(
        product_id="p_grace_cushion",
        seller_id="s_grace",
        seller_name="Grace",
        title="Hand-embroidered linen cushion cover",
        category="home textiles",
        variants=["natural", "sage"],
        price_usd=32.00,
        capacity_per_week=3,
        ship_days=3,
        ship_from_city="Detroit",
    ),
]
