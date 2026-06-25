"""Exercise the full Option B flow in-process."""
from pathlib import Path
from fastapi.testclient import TestClient
from app.db import init_db
from app.ingest import ingest_directory
from app.main import app

init_db()
print("SEED:", ingest_directory(Path("sample-bacaro"), "vepro")["ingested"])

c = TestClient(app)

print("\n[catalog] search 'genio':")
print(" ", c.get("/search?q=genio").json())

print("\n[daemon] resolve stable/x86_64:")
print(" ", c.get("/resolve/org.haiku.genio?channel=stable&arch=x86_64").json())

print("\n[auth] register:")
tok = c.post("/auth/register", json={"email":"andrea@vepro.it","password":"spritz123"}).json()["access_token"]
print("  token:", tok[:24], "...")
H = {"Authorization": f"Bearer {tok}"}

print("\n[web] queue install (add to library):")
print(" ", c.post("/library/org.haiku.genio", json={"channel":"stable","arch":"x86_64"}, headers=H).json())

print("\n[daemon] poll /library/pending:")
print(" ", c.get("/library/pending", headers=H).json())

print("\n[daemon] confirm installed:")
print(" ", c.post("/library/org.haiku.genio/installed", headers=H).json())

print("\n[web] my library (state should be installed):")
print(" ", c.get("/library", headers=H).json())

print("\n[auth] login round-trip:")
r = c.post("/auth/login", json={"email":"andrea@vepro.it","password":"spritz123"})
print("  login status:", r.status_code, "| wrong pw:", c.post("/auth/login", json={"email":"andrea@vepro.it","password":"x"}).status_code)
