import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

# Ensure project root is available for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.license import LicenseService


def main() -> None:
    """Parse command-line arguments and generate license key."""
    parser = argparse.ArgumentParser(
        description="MediaFlow Private License Key Generator",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--days", type=int, help="Number of days until license expiration")
    group.add_argument("--date", type=str, help="Explicit expiration date (YYYY-MM-DD)")
    group.add_argument("--lifetime", action="store_true", help="Generate permanent lifetime license")

    parser.add_argument("--tier", type=str, default="standard", help="License tier (standard, pro)")
    parser.add_argument("--user", type=str, default="", help="Customer name, email, or identifier")
    parser.add_argument("--secret", type=str, default=None, help="Custom signing secret override")

    args = parser.parse_args()

    exp_date: date | None = None
    if args.lifetime:
        exp_date = None
        exp_display = "Lifetime (Permanent)"
    elif args.date:
        try:
            exp_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            exp_display = exp_date.strftime("%Y-%m-%d")
        except ValueError:
            print("Error: Date must be formatted as YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    elif args.days:
        if args.days <= 0:
            print("Error: --days must be greater than 0.", file=sys.stderr)
            sys.exit(1)
        exp_date = (datetime.now() + timedelta(days=args.days)).date()
        exp_display = f"{exp_date.strftime('%Y-%m-%d')} ({args.days} days)"

    key = LicenseService.generate_key(
        expires_at=exp_date,
        tier=args.tier,
        uid=args.user,
        secret_key=args.secret,
    )

    print("=" * 50)
    print("MediaFlow License Key Generated Successfully")
    print("=" * 50)
    print(f"Product Key : {key}")
    print(f"Expires On  : {exp_display}")
    print(f"Tier        : {args.tier.upper()}")
    if args.user:
        print(f"Issued To   : {args.user}")
    print("=" * 50)


if __name__ == "__main__":
    main()
