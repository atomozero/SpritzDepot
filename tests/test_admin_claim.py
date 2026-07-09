"""The JWT carries an `adm` claim so the UI can show the admin link only to
admins. This is UI-only: server authorization still re-checks is_admin, so a
tampered adm claim grants nothing. Throwaway DB.

Checks: admin (bootstrapped first user) gets adm=true, a normal user adm=false,
both at register and login; the nav link is hidden by default in the template.
"""
import os
import pathlib
import base64
import json

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_BOOTSTRAP_ADMIN"] = "1"   # first user becomes admin
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_admin_claim.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_admin_claim.db" + s).unlink(missing_ok=True)

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import app

init_db()
c = TestClient(app)


def adm_claim(token: str):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload)).get("adm")


# first registered user -> admin (bootstrap)
admin_tok = c.post("/auth/register",
                   json={"email": "boss@x.io", "password": "longenoughpass1"}
                   ).json()["access_token"]
assert adm_claim(admin_tok) is True, "admin token must carry adm=true"
print("admin register     -> ok (adm=true)")

# second user -> normal
user_tok = c.post("/auth/register",
                  json={"email": "joe@x.io", "password": "longenoughpass1"}
                  ).json()["access_token"]
assert adm_claim(user_tok) is False, "normal user must carry adm=false"
print("normal register    -> ok (adm=false)")

# login carries the claim too
relog = c.post("/auth/login",
               json={"email": "boss@x.io", "password": "longenoughpass1"}
               ).json()["access_token"]
assert adm_claim(relog) is True
print("admin login        -> ok (adm=true)")

# the claim is cosmetic: server still enforces. A normal user hitting an admin
# route is refused regardless of what the UI would show.
r = c.post("/repo/build", headers={"Authorization": f"Bearer {user_tok}"})
assert r.status_code in (401, 403), f"normal user must be refused, got {r.status_code}"
print("server enforces    -> ok (normal user refused on /repo/build)")

# the nav link is hidden by default in the shell (JS reveals it for admins)
home = c.get("/").text
assert 'id="nav-admin"' in home and 'display:none' in home.split('id="nav-admin"')[1][:60]
print("nav link hidden    -> ok (revealed client-side for admins)")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_admin_claim.db" + s).unlink(missing_ok=True)
print("\nPASS: admin claim in JWT + hidden nav link")
