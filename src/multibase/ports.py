# multibase — shared port and database strategy

PORT_OFFSETS = {
    "kong": 1,        # API gateway (entry point for this project)
    "auth": 2,        # GoTrue
    "rest": 3,        # PostgREST
    "studio": 4,      # Studio URL parameter
    "inbucket": 5,    # Email testing
    "functions": 6,   # Edge Runtime
    "analytics": 7,   # Logflare
}

SHARED_PORTS = {
    "shared_kong": 8000,       # shared gateway admin
    "shared_db": 5432,         # internal only
    "shared_realtime": 4000,   # realtime engine
    "shared_studio": 3000,     # studio UI
    "shared_logflare": 5000,   # analytics
    "shared_storage": 9000,    # S3-compatible
    "shared_pgmeta": 9100,     # DB introspection
}
