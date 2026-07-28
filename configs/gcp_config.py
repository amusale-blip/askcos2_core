import os


class GCPConfig:
    """Centralized configuration for GCP, Vertex AI, and Cloud Run settings."""

    USE_VERTEX_AI: bool = os.environ.get("USE_VERTEX_AI", "1").lower() in ("1", "true", "yes")
    VERTEX_PROJECT: str = os.environ.get("VERTEX_PROJECT", "x-woodward")
    VERTEX_LOCATION: str = os.environ.get("VERTEX_LOCATION", "us-central1")

    # Vertex AI Endpoint IDs
    ONMT_MOLTRANS_ENDPOINT_ID: str = os.environ.get("VERTEX_ENDPOINT_ID", "2804467684119412736")
    RETROCHIMERA_ENDPOINT_ID: str = os.environ.get("RETROCHIMERA_VERTEX_ENDPOINT_ID", "2012551031283515392")
    AIZYNTHFINDER_ENDPOINT_ID: str = os.environ.get("AIZYNTHFINDER_VERTEX_ENDPOINT_ID", "1495270392833507328")

