"""Command-line license key generator utility for MediaFlow."""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

# Ensure project root is available for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_config
from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.services.hardware import get_machine_id
from app.services.license import LicenseService


def main() -> None:
    """Parse command-line arguments and generate Ed25519-signed license key."""
    parser = argparse.ArgumentParser(
        description="MediaFlow Vendor License Key Generator (Ed25519 Asymmetric)",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--days", type=int, help="Number of days until license expiration")
    group.add_argument("--date", type=str, help="Explicit expiration date (YYYY-MM-DD)")
    group.add_argument("--lifetime", action="store_true", help="Generate permanent lifetime license")

    parser.add_argument(
        "--activate",
        action="store_true",
        help="Automatically activate the local MediaFlow installation with the generated key",
    )

    parser.add_argument("--tier", type=str, default="pro", help="License tier (standard, pro)")
    parser.add_argument("--hwid", type=str, default=None, help="Customer Machine ID (default: current machine if --activate, else ANY)")
    parser.add_argument("--user", type=str, default="Owner", help="Customer name, email, or identifier")
    parser.add_argument("--private-key", type=str, default=None, help="Vendor Ed25519 private key (Base64 or file path)")
    parser.add_argument("--secret", type=str, default=None, help="Legacy secret parameter override")

    args = parser.parse_args()

    # Determine expiration
    exp_date: date | None = None
    if args.days:
        if args.days <= 0:
            print("Error: --days must be greater than 0.", file=sys.stderr)
            sys.exit(1)
        exp_date = (datetime.now() + timedelta(days=args.days)).date()
        exp_display = f"{exp_date.strftime('%Y-%m-%d')} ({args.days} day{'s' if args.days != 1 else ''})"
    elif args.date:
        try:
            exp_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            exp_display = exp_date.strftime("%Y-%m-%d")
        except ValueError:
            print("Error: Date must be formatted as YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        exp_date = None
        exp_display = "Lifetime (Permanent)"

    # Determine Machine ID
    if args.hwid:
        target_hwid = args.hwid
    elif args.activate:
        target_hwid = get_machine_id()
    else:
        target_hwid = "ANY"

    signing_key = args.private_key or args.secret

    key = LicenseService.generate_key(
        expires_at=exp_date,
        tier=args.tier,
        hwid=target_hwid,
        uid=args.user,
        private_key=signing_key,
    )

    print("=" * 60)
    print("MediaFlow License Key Generated Successfully")
    print("=" * 60)
    print(f"Product Key : {key}")
    print(f"Expires On  : {exp_display}")
    print(f"Tier        : {args.tier.upper()}")
    print(f"Machine ID  : {target_hwid.upper()}")
    if args.user:
        print(f"Issued To   : {args.user}")
    print("=" * 60)

    if args.activate:
        cfg = get_config()
        repo = SettingsRepository(DatabaseManager(db_path=cfg.db_path))
        service = LicenseService(settings_repo=repo)
        info = service.activate(key)
        if info.is_valid:
            print(f"SUCCESS: MediaFlow locally activated ({info.tier.upper()} Tier, {exp_display})!")
            print(f"Database: {cfg.db_path.resolve()}")
        else:
            print(f"FAILED to activate locally: {info.message}", file=sys.stderr)
            sys.exit(1)



if __name__ == "__main__":
    main()
