"""Seed one real test book (valid PDF) into the live Supabase project.

Phase 2 verification helper: gives the bot something to find and deliver.
Idempotent — re-running updates the same rows. Remove later with --delete.

Usage:
    python scripts/seed_test_book.py          # insert/update the test book
    python scripts/seed_test_book.py --delete  # remove it again

Inserts directly with the *real* schema columns (books.source_ref,
unique(title,author,language)) — the legacy ``db.upsert_book`` still targets a
v1 ``source_id`` column and is unused here.
"""

from __future__ import annotations

import sys

from bookbot import db
from bookbot.config import get_settings

TITLE = "BookBot Test Kitob"
AUTHOR = "Test Muallif"
LANGUAGE = "uz"
STORAGE_PATH = "test/bookbot-test.pdf"


def _minimal_pdf(text: str) -> bytes:
    """Build a tiny but structurally valid single-page PDF with correct xref."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\nBT /F1 24 Tf 72 700 Td (%s) Tj ET\nendstream"
        % (len(text) + 26, text.encode("latin-1", "replace")),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objs) + 1)
    out += b"startxref\n%d\n%%%%EOF" % xref_pos
    return bytes(out)


def _book_id() -> str | None:
    client = db.get_client()
    res = (
        client.table("books")
        .select("id")
        .eq("title", TITLE)
        .eq("author", AUTHOR)
        .eq("language", LANGUAGE)
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def seed() -> None:
    client = db.get_client()
    pdf = _minimal_pdf("BookBot test PDF")

    db.upload_file(STORAGE_PATH, pdf, "application/pdf")
    print(f"✓ Uploaded {len(pdf)} bytes to storage: {STORAGE_PATH}")

    res = (
        client.table("books")
        .upsert(
            {
                "title": TITLE,
                "author": AUTHOR,
                "language": LANGUAGE,
                "source": "admin",
                "source_ref": "seed:test",
            },
            on_conflict="title,author,language",
        )
        .execute()
    )
    book_id = res.data[0]["id"]
    print(f"✓ Book row: {book_id}")

    client.table("book_files").upsert(
        {
            "book_id": book_id,
            "format": "pdf",
            "storage_path": STORAGE_PATH,
            "size_bytes": len(pdf),
        },
        on_conflict="book_id,format",
    ).execute()
    print("✓ book_files row (pdf) upserted")
    print(f'\nDone. Search the bot for "{TITLE}" in PDF mode.')


def delete() -> None:
    client = db.get_client()
    book_id = _book_id()
    if book_id:
        client.table("books").delete().eq("id", book_id).execute()  # cascades to files
        print(f"✓ Deleted book {book_id} (+ files)")
    settings = get_settings()
    try:
        client.storage.from_(settings.supabase_bucket).remove([STORAGE_PATH])
        print(f"✓ Removed storage object {STORAGE_PATH}")
    except Exception as exc:  # noqa: BLE001
        print(f"(storage remove skipped: {exc})")


if __name__ == "__main__":
    if "--delete" in sys.argv:
        delete()
    else:
        seed()
