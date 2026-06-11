"""Kong declarative config (kong.yml) generator for multibase."""
from __future__ import annotations

from multibase.config import MultibaseConfig, ProjectConfig
from multibase.orchestrator import (
    KONG_OFFSET,
    AUTH_OFFSET,
    REST_OFFSET,
    STUDIO_OFFSET,
    INBUCKET_OFFSET,
    FUNCTIONS_OFFSET,
    IMAGES,
)


def generate_kong_yaml(cfg: MultibaseConfig) -> str:
    """Generate Kong declarative config with per-project routes."""
    lines = [
        "# multibase — Kong declarative config (auto-generated)",
        "# Do NOT edit. Run `multibase compose` to regenerate.",
        "_format_version: \"3.0\"",
        "_transform: true",
        "",
        "services:",
    ]

    # Shared services
    lines.append("  # ── SHARED SERVICES ──")

    lines += _shared_route("realtime", IMAGES["realtime"], "realtime", 4000,
                           ["/realtime/v1/"])
    lines.append("")
    lines += _shared_route("pgmeta", IMAGES["pgmeta"], "pgmeta", 8080,
                           ["/pgmeta/v1/"])
    lines.append("")

    if cfg.shared.storage:
        lines += _shared_route("storage", IMAGES["storage"], "storage", 5000,
                               ["/storage/v1/"])
        lines.append("")

    if cfg.shared.analytics:
        lines += _shared_route("logflare", IMAGES["logflare"], "logflare", 4000,
                               ["/logs/"])
        lines.append("")

    # Per-project services
    lines.append("  # ── PER-PROJECT SERVICES ──")

    for proj in cfg.projects:
        lines += _project_routes(proj)

    lines.append("")

    # upstreams
    lines.append("upstreams:")
    for proj in cfg.projects:
        for svc, upstream_port in [
            ("auth", proj.port_base + AUTH_OFFSET),
            ("rest", proj.port_base + REST_OFFSET),
            ("inbucket", proj.port_base + INBUCKET_OFFSET),
            ("functions", proj.port_base + FUNCTIONS_OFFSET),
        ]:
            lines.append(f"  - name: {proj.name}-{svc}-upstream")
            lines.append(f"    targets:")
            lines.append(f"      - target: host.docker.internal:{upstream_port}")

    # Shared upstreams
    lines.append(f"  - name: realtime-upstream")
    lines.append(f"    targets:")
    lines.append(f"      - target: realtime:4000")
    lines.append(f"  - name: pgmeta-upstream")
    lines.append(f"    targets:")
    lines.append(f"      - target: pgmeta:8080")

    if cfg.shared.storage:
        lines.append(f"  - name: storage-upstream")
        lines.append(f"    targets:")
        lines.append(f"      - target: storage:5000")

    if cfg.shared.analytics:
        lines.append(f"  - name: logflare-upstream")
        lines.append(f"    targets:")
        lines.append(f"      - target: logflare:4000")

    return "\n".join(lines) + "\n"


def _shared_route(name: str, image: str, upstream: str, port: int, paths: list[str]) -> list[str]:
    return [
        f"  - name: {name}",
        f"    url: http://{upstream}:{port}",
        f"    routes:",
        f"      - name: {name}-route",
        f"        paths:",
    ] + [f"          - {path!r}" for path in paths]


def _project_routes(proj: ProjectConfig) -> list[str]:
    lines = []
    for svc, upstream_port, paths in [
        ("auth", proj.port_base + AUTH_OFFSET, ["/auth/v1/"]),
        ("rest", proj.port_base + REST_OFFSET, ["/rest/v1/"]),
        ("inbucket", proj.port_base + INBUCKET_OFFSET, ["/inbucket/"]),
        ("functions", proj.port_base + FUNCTIONS_OFFSET, ["/functions/v1/"]),
    ]:
        lines.append(f"  - name: {proj.name}-{svc}")
        lines.append(f"    host: {proj.name}.multibase.local")
        lines.append(f"    routes:")
        lines.append(f"      - name: {proj.name}-{svc}-route")
        lines.append(f"        hosts: [{proj.name}.multibase.local]")
        lines.append(f"    upstream:")
        lines.append(f"      name: {proj.name}-{svc}-upstream")
        lines.append("")
    return lines


def save_kong_yaml(cfg: MultibaseConfig, out_path: str = "kong.yml") -> None:
    """Save the generated Kong config to disk."""
    content = generate_kong_yaml(cfg)
    with open(out_path, "w") as f:
        f.write(content)
