import os

DATABASE = "askcos"

# On-disk buyables preload cache (MongoPricer). Override via env or pricer.buyables_cache_dir in module_config.
BUYABLES_CACHE_DIR = os.environ.get(
    "BUYABLES_CACHE_DIR",
    "/usr/local/askcos-data/db/buyables",
)

MONGO = {
    "host": os.environ.get("MONGO_HOST", "0.0.0.0"),
    "port": int(os.environ.get("MONGO_PORT", 27017)),
    "username": os.environ.get("MONGO_USER"),
    "password": os.environ.get("MONGO_PW"),
    "authSource": os.environ.get("MONGO_AUTH_DB", "admin"),
    "connect": False,
}
