"""Vendor utility to generate Ed25519 asymmetric cryptographic key pairs."""

import argparse
import base64
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def main() -> None:
    """Generate Ed25519 keypair and display base64 and PEM representations."""
    parser = argparse.ArgumentParser(description="MediaFlow Vendor Keypair Generator")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Optional directory to save private_key.pem and public_key.pem",
    )
    args = parser.parse_args()

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_raw = private_key.private_bytes_raw()
    pub_raw = public_key.public_bytes_raw()

    priv_b64 = base64.b64encode(priv_raw).decode("utf-8")
    pub_b64 = base64.b64encode(pub_raw).decode("utf-8")

    print("=" * 60)
    print("MediaFlow Ed25519 Keypair Generated Successfully")
    print("=" * 60)
    print("PUBLIC KEY (Safe to embed in desktop client app / config):")
    print(f"  {pub_b64}")
    print()
    print("PRIVATE KEY (KEEP CONFIDENTIAL! Never include in client app builds):")
    print(f"  {priv_b64}")
    print("=" * 60)

    if args.output_dir:
        out_path = Path(args.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        priv_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        priv_file = out_path / "license_private.pem"
        pub_file = out_path / "license_public.pem"

        priv_file.write_bytes(priv_pem)
        pub_file.write_bytes(pub_pem)
        print(f"Saved private key to: {priv_file}")
        print(f"Saved public key to:  {pub_file}")


if __name__ == "__main__":
    main()
