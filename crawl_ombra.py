"""Prefetch every ombra (github-latest) app's latest release into the snapshot
cache. Run headless from cron or a systemd timer so /resolve and
/library/pending serve ombra from the DB instead of hitting GitHub live.

    # once
    python crawl_ombra.py

    # every 6 hours via cron (matches the snapshot TTL)
    0 */6 * * *  cd /srv/spritz && .venv/bin/python crawl_ombra.py

Set SPRITZ_GITHUB_TOKEN in the environment to lift the 60 req/h anonymous
GitHub rate limit (5000/h authenticated).
"""
from app.db import init_db, engine
from app.ombra_crawler import crawl_ombra
from sqlmodel import Session

init_db()
with Session(engine) as session:
    result = crawl_ombra(session)

print(f"ombra crawl: {result.total} apps, {result.resolved} resolved, "
      f"{result.errors} with errors")
