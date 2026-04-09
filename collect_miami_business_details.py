#!/usr/bin/env python3
"""
CLI entry point for collecting public business leads into details.txt.
"""

from __future__ import annotations

import argparse

from lead_service import collect_businesses, write_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect publicly visible business details for a location."
    )
    parser.add_argument(
        "--location",
        default="",
        help="Fallback single location string, for example 'Miami, Florida'.",
    )
    parser.add_argument(
        "--country",
        default="United States",
        help="Country to search in.",
    )
    parser.add_argument(
        "--state",
        default="Florida",
        help="State or province to search in.",
    )
    parser.add_argument(
        "--district",
        default="",
        help="District or neighborhood to narrow the search.",
    )
    parser.add_argument(
        "--city",
        default="Miami",
        help="City to search in.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Number of businesses to write (default: 8).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Delay between public site requests in seconds (default: 0.05).",
    )
    parser.add_argument(
        "--output",
        default="details.txt",
        help="Output file path (default: details.txt).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _, businesses = collect_businesses(
        location=args.location,
        country=args.country,
        state=args.state,
        district=args.district,
        city=args.city,
        limit=max(1, args.limit),
        delay_seconds=max(0.0, args.delay),
    )
    write_output(args.output, businesses)
    print(f"Wrote {len(businesses)} businesses to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
