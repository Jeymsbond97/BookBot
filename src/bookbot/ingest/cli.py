"""Command-line entry point for seeding the catalog.

Usage:
    python -m bookbot.ingest.cli gutenberg --limit 20 --lang en
    python -m bookbot.ingest.cli librivox  --limit 10
"""

from __future__ import annotations

import argparse
import sys

from . import gutenberg, librivox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bookbot-ingest",
        description="Seed the BookBot catalog from public-domain sources.",
    )
    sub = parser.add_subparsers(dest="source", required=True)

    g = sub.add_parser("gutenberg", help="Ingest ebooks (PDF/EPUB) from Project Gutenberg.")
    g.add_argument("--limit", type=int, default=20, help="Number of books to ingest.")
    g.add_argument("--lang", default="en", help="Two-letter language code (default: en).")

    l = sub.add_parser("librivox", help="Ingest audiobooks (MP3) from LibriVox/Archive.")
    l.add_argument("--limit", type=int, default=10, help="Number of audiobooks to ingest.")

    args = parser.parse_args(argv)

    if args.source == "gutenberg":
        count = gutenberg.ingest(limit=args.limit, lang=args.lang)
    elif args.source == "librivox":
        count = librivox.ingest(limit=args.limit)
    else:  # pragma: no cover - argparse enforces choices
        parser.error(f"unknown source: {args.source}")
        return 2

    print(f"\n✅ Done. Ingested {count} item(s) from {args.source}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
