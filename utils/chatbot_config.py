import os
from typing import Any
from configs import db_config
from pymongo import MongoClient, errors
from utils import register_util

CHATBOT_SECRET_KEYS = [
    "CLAUDE_API_KEY",
    "CLAUDE_MODEL",
    "CHATBOT_SYSTEM_PROMPT",
]

_CHATBOT_ENABLED = os.environ.get("VITE_ENABLE_CHATBOT", "True").lower() == "true"


class ChatbotConfigController:

    prefixes = ["chatbot_config"]
    methods_to_bind: dict[str, list[str]] = {}

    def __init__(self, util_config: dict[str, Any] | None):
        util_config = util_config or {
            "engine": "db",
            "database": "askcos",
            "collection": "chatbot_config",
        }

        assert util_config["engine"] == "db", \
            "Only the 'db' engine is supported for chatbot config controller"

        self.client = MongoClient(serverSelectionTimeoutMS=1000, **db_config.MONGO)

        database = util_config["database"]
        collection = util_config["collection"]

        try:
            self.client.server_info()
        except errors.ServerSelectionTimeoutError:
            raise ValueError("Cannot connect to MongoDB to load chatbot config")

        self.collection = self.client[database][collection]

        for key in CHATBOT_SECRET_KEYS:
            value = os.environ.get(key)
            if value is None:
                continue
            self.collection.update_one(
                {"key": key},
                {"$set": {"value": value}},
                upsert=True,
            )

    def get(self, key: str) -> str | None:
        doc = self.collection.find_one({"key": key})
        value = doc.get("value") if doc else None
        return value if isinstance(value, str) else None


if _CHATBOT_ENABLED:
    ChatbotConfigController = register_util(
        name="chatbot_config_controller"
    )(ChatbotConfigController)
