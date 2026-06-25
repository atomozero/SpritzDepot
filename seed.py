"""Seed the cache from the local sample bàcaro (no git needed)."""
from pathlib import Path
from app.db import init_db
from app.ingest import ingest_directory

init_db()
report = ingest_directory(Path("sample-bacaro"), "vepro")
print("Ingested:", report["ingested"])
print("Failed:", report["failed"])
