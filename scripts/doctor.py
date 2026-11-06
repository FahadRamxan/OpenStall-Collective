"""The PayPal doctor in a terminal: is this setup ready to hold a buyer's money and pay makers through PayPal?

    python scripts/doctor.py           the checks, then the PayPal products and how far each has got
    python scripts/doctor.py --checks  the checks only

It reads .env as the API does, so in sandbox mode it asks PayPal for a token and reads the registered webhook back;
nothing else is sent. It names a missing key, never a key's value. It exits with 1 when a check fails.
"""

import argparse
import sys

from openstall_api.adapters import get_registry
from openstall_api.doctor import doctor_report

MARKS = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL", "skip": "skip"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checks", action="store_true", help="the checks only, without the products table")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Lucía's name on a Windows console

    report = doctor_report(get_registry())
    print(f"PayPal doctor, {report.mode} mode\n")
    for check in report.checks:
        print(f"  {MARKS[check.status]}  {check.name}: {check.detail}")
    if not args.checks:
        print("\nPayPal products\n")
        width = max(len(product.name) for product in report.products)
        for product in report.products:
            print(f"  {product.name:<{width}}  {product.state_words}")
            print(f"  {'':<{width}}  {product.evidence}")
    failed = [check.name for check in report.checks if check.status == "fail"]
    print(f"\n{'Failed: ' + ', '.join(failed) if failed else 'Nothing failed.'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
