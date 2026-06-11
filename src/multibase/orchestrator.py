"""Docker Compose generation and lifecycle management."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from multibase.config import MultibaseConfig, ProjectConfig


# ── Port offset constants ──────────────────────────────
KONG_OFFSET = 1
AUTH_OFFSET = 2
REST_OFFSET = 3
STUDIO_OFFSET = 4
INBUCKET_OFFSET = 5
FUNCTIONS_OFFSET = 6
ANALYTICS_OFFSET = 7
VECTOR_OFFSET = 8


# ── Image tags ─────────────────────────────────────────
IMAGES = {
    "postgres": "public.ecr.aws/supabase/postgres:17.6.1.132",
    "studio": "public.ecr.aws/supabase/studio:2026.06.03-sha-0bca601",
    "kong": "public.ecr.aws/supabase/kong:2.8.1",
    "realtime": "public.ecr.aws/supabase/realtime:v2.103.2",
    "gotrue": "public.ecr.aws/supabase/gotrue:v2.189.0",
    "postgrest": "public.ecr.aws/supabase/postgrest:v14.12",
    "pgmeta": "public.ecr.aws/supabase/postgres-meta:v0.96.6",
    "inbucket": "public.ecr.aws/supabase/inbucket:2.0.0",
    "storage": "public.ecr.aws/supabase/storage-api:v1.60.4",
    "logflare": "public.ecr.aws/supabase/logflare:1.37.1",
    "vector": "public.ecr.aws/supabase/vector:0.53.0-alpine",
    "edge_runtime": "public.ecr.aws/supabase/edge-runtime:v1.74.0",
}


def _project_env(proj: ProjectConfig) -> dict:
    """Environment variables shared by all services for a given project."""
    base = proj.port_base
    return {
        "PROJECT_NAME": proj.name,
        "PORT_BASE": str(base),
        "KONG_PORT": str(base + KONG_OFFSET),
        "AUTH_PORT": str(base + AUTH_OFFSET),
        "REST_PORT": str(base + REST_OFFSET),
        "STUDIO_PORT": str(base + STUDIO_OFFSET),
        "INBUCKET_PORT": str(base + INBUCKET_OFFSET),
        "FUNCTIONS_PORT": str(base + FUNCTIONS_OFFSET),
    }


def build_shared_services(cfg: MultibaseConfig) -> dict:
    """Build docker-compose YAML dict for shared services."""
    S = cfg.shared
    svc = {}

    # ── Postgres (multi-database) ──
    pg_volumes = [
        "multibase_db_data:/var/lib/postgresql/data",
        "./src/multibase/templates/init-db.sh:/docker-entrypoint-initdb.d/00-multibase.sh:ro",
    ]
    pg_cmd = []
    for proj in cfg.projects:
        db_name = proj.name.replace("-", "_")
        pg_cmd.append(f"CREATE DATABASE {db_name};")

    # Write project list for init script
    projects_txt = "\n".join(p.name for p in cfg.projects)
    Path("projects.txt").write_text(projects_txt)

    svc["db"] = {
        "image": S.db_image,
        "container_name": "multibase-db",
        "healthcheck": {
            "test": ["CMD", "pg_isready", "-U", "postgres", "-q"],
            "interval": "5s",
            "timeout": "2s",
            "retries": 10,
        },
        "volumes": pg_volumes,
        "environment": {
            "POSTGRES_PASSWORD": "postgres",
            "POSTGRES_HOST": "/var/run/postgresql",
            "MULTIBASE_CONFIG": "/etc/multibase/projects.txt",
        },
        "labels": {"multibase.service": "db"},
    }

    # ── Kong (shared API gateway) ──
    svc["kong"] = {
        "image": IMAGES["kong"],
        "container_name": "multibase-kong",
        "ports": [
            f"{S.kong_port}:8000/tcp",
            f"{S.kong_port + 1}:8001/tcp",  # admin API
        ],
        "environment": {
            "KONG_DATABASE": "off",
            "KONG_DECLARATIVE_CONFIG": "/etc/kong/kong.yml",
            "KONG_PROXY_ACCESS_LOG": "/dev/stdout",
            "KONG_ADMIN_ACCESS_LOG": "/dev/stdout",
            "KONG_PROXY_ERROR_LOG": "/dev/stderr",
            "KONG_ADMIN_ERROR_LOG": "/dev/stderr",
            "KONG_ADMIN_LISTEN": f"0.0.0.0:{S.kong_port + 1}",
        },
        "volumes": ["./kong.yml:/etc/kong/kong.yml:ro"],
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {"multibase.service": "kong"},
    }

    # ── Studio ──
    studio_env = {
        "STUDIO_PG_META_URL": f"http://pgmeta:{S.kong_port + 2}",  # internal port
        "POSTGRES_PASSWORD": "postgres",
        "SUPABASE_URL": f"http://localhost:{S.kong_port}",
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiJ9.placeholder",
        "SUPABASE_SERVICE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoic2VydmljZV9yb2xlIn0.placeholder",
    }
    svc["studio"] = {
        "image": IMAGES["studio"],
        "container_name": "multibase-studio",
        "ports": [f"{S.studio_port}:3000/tcp"],
        "environment": studio_env,
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {"multibase.service": "studio"},
    }

    # ── Realtime ──
    svc["realtime"] = {
        "image": IMAGES["realtime"],
        "container_name": "multibase-realtime",
        "environment": {
            "DB_HOST": "db",
            "DB_PORT": "5432",
            "DB_NAME": "postgres",
            "DB_USER": "postgres",
            "DB_PASSWORD": "postgres",
            "DB_AFTER_CONNECT_QUERY": _build_realtime_query(cfg),
            "PORT": "4000",
        },
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {"multibase.service": "realtime"},
    }

    # ── Postgres Meta ──
    svc["pgmeta"] = {
        "image": IMAGES["pgmeta"],
        "container_name": "multibase-pgmeta",
        "environment": {
            "PG_META_PORT": "8080",
            "PG_META_DB_HOST": "db",
            "PG_META_DB_PORT": "5432",
            "PG_META_DB_NAME": "postgres",
            "PG_META_DB_USER": "postgres",
            "PG_META_DB_PASSWORD": "postgres",
        },
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {"multibase.service": "pgmeta"},
    }

    # ── Analytics / Logflare ──
    if S.analytics:
        svc["logflare"] = {
            "image": IMAGES["logflare"],
            "container_name": "multibase-logflare",
            "environment": {
                "LOGFLARE_SINGLE_TENANT": "true",
                "LOGFLARE_SUPABASE_URL": f"http://kong:{S.kong_port}",
                "LOGFLARE_API_KEY": "placeholder-key",
            },
            "depends_on": {"db": {"condition": "service_healthy"}},
            "labels": {"multibase.service": "logflare"},
        }

        svc["vector"] = {
            "image": IMAGES["vector"],
            "container_name": "multibase-vector",
            "depends_on": {"db": {"condition": "service_healthy"}},
            "labels": {"multibase.service": "vector"},
        }

    # ── Storage ──
    if S.storage:
        svc["storage"] = {
            "image": IMAGES["storage"],
            "container_name": "multibase-storage",
            "environment": {
                "ANON_KEY": "placeholder-anon-key",
                "SERVICE_KEY": "placeholder-service-key",
                "POSTGREST_URL": "http://kong:8000/rest/v1/",
                "PGRST_JWT_SECRET": "placeholder-jwt-secret",
                "DATABASE_URL": "postgres://postgres:postgres@db:5432/postgres",
                "FILE_SIZE_LIMIT": "52428800",
                "STORAGE_BACKEND": "file",
                "FILE_STORAGE_BACKEND_PATH": "/var/lib/storage",
            },
            "volumes": ["multibase_storage:/var/lib/storage"],
            "depends_on": {"db": {"condition": "service_healthy"}},
            "labels": {"multibase.service": "storage"},
        }

    return {
        "version": "3.8",
        "services": svc,
        "volumes": {
            "multibase_db_data": {},
            "multibase_storage": {},
        },
    }


def _build_realtime_query(cfg: MultibaseConfig) -> str:
    """SQL that realtime runs after connecting to register all project DBs."""
    queries = [
        "CREATE EXTENSION IF NOT EXISTS pglogical",
        "ALTER SYSTEM SET wal_level = logical",
    ]
    for proj in cfg.projects:
        db_name = proj.name.replace("-", "_")
        queries.append(f"SELECT pglogical.create_node(node_name := 'multibase_{db_name}', dsn := 'host=db port=5432 dbname={db_name}')")
    return "; ".join(queries)


def build_project_services(proj: ProjectConfig, cfg: MultibaseConfig) -> dict:
    """Build docker-compose YAML dict for per-project services."""
    base = proj.port_base
    db_name = proj.name.replace("-", "_")
    jwt_secret = f"super-secret-jwt-{proj.name}-token"
    anon_key = f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Intcm9sZSI6ImFub24ifQ.{proj.name}-anon"
    service_key = f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Intcm9sZSI6InNlcnZpY2Vfcm9sZSJ9.{proj.name}-svc"

    svc = {}

    # ── GoTrue (Auth) ──
    svc["auth"] = {
        "image": IMAGES["gotrue"],
        "container_name": f"multibase-auth-{proj.name}",
        "ports": [f"{base + AUTH_OFFSET}:9999/tcp"],
        "environment": {
            "GOTRUE_JWT_SECRET": jwt_secret,
            "GOTRUE_DB_DRIVER": "postgres",
            "GOTRUE_DB_DATABASE_URL": f"postgres://postgres:postgres@multibase-db:5432/{db_name}",
            "GOTRUE_SITE_URL": "http://localhost:3000",
            "GOTRUE_MAILER_AUTOCONFIRM": "true",
            "PORT": "9999",
        },
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {
            "multibase.service": "auth",
            "multibase.project": proj.name,
        },
    }

    # ── PostgREST (REST API) ──
    svc["rest"] = {
        "image": IMAGES["postgrest"],
        "container_name": f"multibase-rest-{proj.name}",
        "ports": [f"{base + REST_OFFSET}:3000/tcp"],
        "environment": {
            "PGRST_DB_URI": f"postgres://postgres:postgres@multibase-db:5432/{db_name}",
            "PGRST_DB_SCHEMA": "public",
            "PGRST_DB_ANON_ROLE": "anon",
            "PGRST_JWT_SECRET": jwt_secret,
            "PGRST_DB_EXTRA_SEARCH_PATH": "public,extensions",
        },
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {
            "multibase.service": "rest",
            "multibase.project": proj.name,
        },
    }

    # ── Inbucket (Email) ──
    svc["inbucket"] = {
        "image": IMAGES["inbucket"],
        "container_name": f"multibase-inbucket-{proj.name}",
        "ports": [
            f"{base + INBUCKET_OFFSET}:9000/tcp",  # UI
            f"{base + INBUCKET_OFFSET + 1}:2500/tcp",  # SMTP
        ],
        "labels": {
            "multibase.service": "inbucket",
            "multibase.project": proj.name,
        },
    }

    # ── Edge Runtime (Functions) ──
    svc["functions"] = {
        "image": IMAGES["edge_runtime"],
        "container_name": f"multibase-functions-{proj.name}",
        "ports": [f"{base + FUNCTIONS_OFFSET}:8081/tcp"],
        "environment": {
            "SUPABASE_URL": f"http://kong:{cfg.shared.kong_port}",
            "SUPABASE_ANON_KEY": anon_key,
            "SUPABASE_SERVICE_KEY": service_key,
            "JWT_SECRET": jwt_secret,
        },
        "volumes": [f"./functions/{proj.name}:/app/functions:ro"],
        "depends_on": {"db": {"condition": "service_healthy"}},
        "labels": {
            "multibase.service": "functions",
            "multibase.project": proj.name,
        },
    }

    return {"version": "3.8", "services": svc}


def generate_compose(cfg: MultibaseConfig) -> dict:
    """Generate the full docker-compose dict."""
    shared = build_shared_services(cfg)
    result = {
        "version": "3.8",
        "services": {},
        "volumes": {},
        "networks": {"multibase": {"driver": "bridge"}},
    }

    # Merge shared services
    for svc_name, svc_def in shared.get("services", {}).items():
        svc_def.setdefault("networks", []).append("multibase")
        result["services"][svc_name] = svc_def

    # Merge shared volumes
    result["volumes"].update(shared.get("volumes", {}))

    # Merge per-project services
    for proj in cfg.projects:
        proj_svcs = build_project_services(proj, cfg)
        for svc_name, svc_def in proj_svcs.get("services", {}).items():
            svc_def.setdefault("networks", []).append("multibase")
            result["services"][f"{svc_name}_{proj.name}"] = svc_def

    return result


# ── Lifecycle commands ────────────────────────────────


def _run_docker_compose(cfg: MultibaseConfig, args: list[str]) -> int:
    """Run docker compose with the generated config."""
    compose = generate_compose(cfg)
    compose_data = yaml.dump(compose, default_flow_style=False)

    cmd = ["docker", "compose", "-p", f"multibase_{cfg.name}", "-f", "-"] + args
    proc = subprocess.run(
        cmd,
        input=compose_data,
        text=True,
        capture_output=False,
    )
    return proc.returncode


def up(cfg: MultibaseConfig, detach: bool = True) -> int:
    """Start all services."""
    args = ["up", "-d"] if detach else ["up"]
    return _run_docker_compose(cfg, args)


def down(cfg: MultibaseConfig, volumes: bool = False) -> int:
    """Stop all services."""
    args = ["down"]
    if volumes:
        args.append("-v")
    return _run_docker_compose(cfg, args)


def ps(cfg: MultibaseConfig) -> int:
    """Show running services."""
    return _run_docker_compose(cfg, ["ps"])


def config(cfg: MultibaseConfig) -> int:
    """Show the resolved docker-compose config."""
    return _run_docker_compose(cfg, ["config"])
