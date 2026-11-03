"""Load the demo world (spec section 2) into the database, bringing its tables up to date first.

    python scripts/seed_demo.py                 add the seeded makers, or bring them back to their seeded state
    python scripts/seed_demo.py --reset         empty every table first
    python scripts/seed_demo.py --with-amina    also seed Amina, who normally joins live over WhatsApp
    python scripts/seed_demo.py --if-empty      seed only a database with no sellers yet (the hosted demo's start)
    python scripts/seed_demo.py --demo-order    also a draft of the story's order (implies --with-amina)

Everything seeded is made up for the demo and marked seeded_demo.
"""

import argparse
import sys
from datetime import date

from sqlalchemy import func, select

from openstall_api.db import migrate, session_scope
from openstall_api.models import Seller
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="empty every table first")
    parser.add_argument("--with-amina", action="store_true", help="also seed Amina")
    parser.add_argument("--if-empty", action="store_true", help="do nothing if any seller exists")
    parser.add_argument("--demo-order", action="store_true", help="also a draft of the story's order")
    args = parser.parse_args(argv)
    if args.reset and args.if_empty:
        parser.error("--reset and --if-empty contradict each other")

    migrate()
    with session_scope() as session:
        if args.if_empty and session.scalar(select(func.count()).select_from(Seller)):
            print("The database already has sellers, so nothing was seeded.")
            return 0
        report = seed(session, with_amina=args.with_amina or args.demo_order, reset=args.reset)
        if args.demo_order:
            order = seed_demo_order(session, date.today())
            print(f"Demo order {DEMO_ORDER_ID}: {len(order.parts)} makers, ${order.total_usd:,.2f}")
    print(f"Seeded: {report.sellers} sellers, {report.products} products, {report.passports} passports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
