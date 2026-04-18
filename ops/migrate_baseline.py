#!/usr/bin/env python3
"""
Pricing baseline migration tool.
Decodes obfuscated baseline files and writes to JSON.
"""
import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path


def _keystream(secret_key_bytes, nonce_bytes, size):
    """Generate XOR keystream using SHA256."""
    buf = b""
    counter = 0
    while len(buf) < size:
        block = hashlib.sha256(
            secret_key_bytes + nonce_bytes + counter.to_bytes(4, "big")
        ).digest()
        buf += block
        counter += 1
    return buf[:size]


def _xor_bytes(left, right):
    """XOR two byte strings."""
    return bytes(a ^ b for a, b in zip(left, right))


def decode_payload(payload_obj, secret_key):
    """
    Decode obfuscated payload.

    Args:
        payload_obj: Dict with format, encoding, nonce, payload, sha256
        secret_key: String key for decryption

    Returns:
        Decoded JSON string

    Raises:
        ValueError: If format, encoding, or checksum invalid
    """
    if payload_obj.get("format") != "pricing-baseline-obf-v1":
        raise ValueError("Unsupported obfuscation format")
    if payload_obj.get("encoding") != "base64":
        raise ValueError("Unsupported encoding")

    nonce = bytes.fromhex(str(payload_obj.get("nonce", "")))
    cipher_bytes = base64.b64decode(payload_obj.get("payload", ""))
    secret_key_bytes = secret_key.encode("utf-8")
    plain_bytes = _xor_bytes(cipher_bytes, _keystream(secret_key_bytes, nonce, len(cipher_bytes)))

    digest = hashlib.sha256(plain_bytes).hexdigest()
    if digest != payload_obj.get("sha256"):
        raise ValueError("Obfuscation checksum failed (sha256 mismatch)")
    return plain_bytes.decode("utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate obfuscated pricing baseline to JSON"
    )
    parser.add_argument("--in", dest="input_file", required=True, help="Input .obf file path")
    parser.add_argument("--out", dest="output_file", required=True, help="Output .json file path")
    parser.add_argument("--key", required=True, help="Decryption key")

    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    # Validate input
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Load and decode
        payload_obj = json.loads(input_path.read_text(encoding="utf-8"))
        decoded_json = decode_payload(payload_obj, args.key)
        decoded_obj = json.loads(decoded_json)

        # Write output
        output_path.write_text(
            json.dumps(decoded_obj, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"Successfully migrated to: {output_path}")
        sys.exit(0)

    except ValueError as e:
        print(f"Decryption error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
