"""Account lifecycle + GDPR endpoints (access, portability, erasure, real logout).

Covers: /auth/me returns the user's data without the password hash; /auth/logout
revokes the current token server-side (stateless JWT -> version bump); the /account
and /privacy pages render with the localized notice; delete-account requires the
password and erases the user row AND every library entry (right to erasure), after
which the token is dead. Throwaway DB, offline.
"""
import os
import pathlib

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_account_gdpr.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_account_gdpr.db" + s).unlink(missing_ok=True)

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import init_db, engine
from app.models import CichetoRow, User, InstallState
from app.main import app

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="x.y.z", name="Z", bacaro="vepro", channels="stable",
                       raw={"id": "x.y.z", "name": "Z"}))
    s.commit()

c = TestClient(app)
tok = c.post("/auth/register",
             json={"email": "gdpr@x.io", "password": "longenoughpass1"}).json()["access_token"]
auth = {"Authorization": f"Bearer {tok}"}
assert c.post("/library/x.y.z", json={"channel": "stable", "arch": "x86_64"},
              headers=auth).status_code == 200

# --- /auth/me: access + portability, password hash never included ---
me = c.get("/auth/me", headers=auth)
assert me.status_code == 200, me.text
body = me.json()
assert body["email"] == "gdpr@x.io", body
assert "password_hash" not in body and "password" not in body, body
assert len(body["library"]) == 1 and body["library"][0]["cicheto_id"] == "x.y.z", body
print("auth/me            -> ok (email + library, no hash)")

# --- /auth/logout: real server-side revoke (stateless -> revokes this token) ---
assert c.post("/auth/logout", headers=auth).json()["status"] == "logged out"
assert c.get("/library", headers=auth).status_code == 401, "token must die on logout"
print("auth/logout        -> ok (token revoked server-side)")

# re-login (the token was revoked, the password still works)
tok2 = c.post("/auth/login",
              json={"email": "gdpr@x.io", "password": "longenoughpass1"}).json()["access_token"]
auth2 = {"Authorization": f"Bearer {tok2}"}

# --- delete-account: wrong password refused (stolen token alone can't erase) ---
bad = c.post("/auth/delete-account", json={"password": "wrongpass9999"}, headers=auth2)
assert bad.status_code == 401, bad.text
print("delete wrong pw    -> ok (401)")

# --- delete-account: correct password erases user + all library rows ---
ok = c.post("/auth/delete-account", json={"password": "longenoughpass1"}, headers=auth2)
assert ok.status_code == 200, ok.text
with Session(engine) as s:
    assert s.exec(select(User).where(User.email == "gdpr@x.io")).first() is None, "user kept"
    assert s.exec(select(InstallState)).all() == [], "library rows kept"
print("delete-account     -> ok (user + library erased, art. 17)")

assert c.get("/library", headers=auth2).status_code == 401, "token must die on deletion"
print("post-delete token  -> ok (rejected)")

# --- pages render, localized notice present ---
assert c.get("/account").status_code == 200
priv = c.get("/privacy", cookies={"lang": "it"}).text
assert "Informativa privacy" in priv and "art. 6.1.b GDPR" in priv, "IT notice missing"
print("privacy/account    -> ok (render + IT notice)")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_account_gdpr.db" + s).unlink(missing_ok=True)
print("\nPASS: account lifecycle + GDPR endpoints")
