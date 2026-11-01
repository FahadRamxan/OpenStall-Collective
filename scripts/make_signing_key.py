"""Make a new Ed25519 key pair for signing trust passports.

Usage: python scripts/make_signing_key.py

Copy the PASSPORT_SIGNING_KEY line into .env, and into the hosting provider's environment. It is
secret: never commit it. The public key is safe to share; anyone can check passports with it.
"""

import argparse

from openstall_trust import generate_keypair


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    private_b64, public_b64 = generate_keypair()
    print(f"PASSPORT_SIGNING_KEY={private_b64}")
    print(f"# public key (safe to share): {public_b64}")


if __name__ == "__main__":
    main()
