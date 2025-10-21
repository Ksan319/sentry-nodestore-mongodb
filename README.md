Sentry NodeStore MongoDB Backend
================================

This package provides a MongoDB-backed implementation of Sentry's NodeStore.

What it does
------------
- Minimal NodeStore backed by MongoDB.
- Stores each node as a single binary JSON payload under `_id`.
- Optional TTL per write (no auto-indexing).

Install
-------
```
pip install -e .
```

Configuration (Sentry)
----------------------
Add to your `sentry.conf.py` (or equivalent settings file):

```
SENTRY_NODESTORE = "sentry_nodestore_mongodb.backend.MongoNodeStorage"
SENTRY_NODESTORE_OPTIONS = {
    "uri": os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
    "database": os.environ.get("MONGO_DB", "sentry_nodestore"),
    "collection": os.environ.get("MONGO_COLLECTION", "nodes"),
    # optional
    "default_ttl": None,  # seconds; default per write when not provided
}
```

Notes:
- If you want automatic expiration, create a TTL index manually on `expires_at` with `expireAfterSeconds=0`.
- Values are stored as UTF‑8 JSON bytes.

Local Testing
-------------
You can test against a local MongoDB or via `mongod` in Docker.

1) Start MongoDB (Docker example):
```
docker run --rm -p 27017:27017 --name mongo mongo:6
```

2) Create and activate a venv, install deps:
```
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest
```

3) Run tests:
```
pytest -q
```

Basic Usage Snippet
-------------------
```
from sentry_nodestore_mongodb.backend import MongoNodeStorage

store = MongoNodeStorage(
    uri="mongodb://localhost:27017",
    database="sentry_nodestore",
    collection="nodes",
)

key = "abcd1234"
value = {"hello": "world", "n": 42}
store.set(key, value, ttl=3600)
assert store.get(key) == value
store.delete(key)
```

Integrating into Sentry Container (self-hosted)
-----------------------------------------------
- Add this package to the Python environment inside Sentry's web/worker images. Typical options:
  - Build a wheel and add it to `onpremise` images, or
  - Add `pip install git+ssh://...` (or a path-mounted wheel) to the build step.

Example (onpremise):
1) Add the requirement to `onpremise` custom requirements file (often `onpremise/requirements.txt`):
```
git+https://your.git.hosting/your-org/sentry-nodestore-mongodb.git@main
```
2) Rebuild images:
```
./install.sh
docker compose build --no-cache web worker cron
docker compose up -d
```
3) Add configuration overrides to `sentry.conf.py` used by the images as shown above (ensure it’s mounted/applied).

Integrating in a local getsentry checkout
----------------------------------------
If you run Sentry from `~/PycharmProjects/getsentry`:
- Install this package into the same virtualenv Sentry uses:
```
pip install -e /Users/admin/PycharmProjects/sentry-nodestore-mongodb
```
- In your settings file used by the devserver (e.g., `~/.sentry/sentry.conf.py` or your project’s `sentry.conf.py`), set `SENTRY_NODESTORE` and options as shown above.
- Run Sentry normally (devserver or runserver). Events created should persist via MongoDB.

Operational Considerations
--------------------------
- If you need automatic expiry, ensure a TTL index exists: `db.nodes.createIndex({"expires_at": 1}, { expireAfterSeconds: 0 })`.
- MongoDB TTL deletions are asynchronous and best-effort.
