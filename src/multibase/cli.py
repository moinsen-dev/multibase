"""multibase CLI — manage multiple Supabase projects on one host."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from multibase import orchestrator
from multibase.config import MultibaseConfig, ProjectConfig
from multibase.kong_config import generate_kong_yaml, save_kong_yaml

app = typer.Typer(
    name="multibase",
    help="Run multiple Supabase projects on one host — share the heavy services, keep projects isolated.",
    no_args_is_help=True,
)

CONFIG_PATH = Path("multibase.yaml")
DEFAULT_PORT_BASE = 54320


def _load_config() -> MultibaseConfig:
    if not CONFIG_PATH.exists():
        typer.echo("❌ multibase.yaml not found. Run `multibase init` first.", err=True)
        raise typer.Exit(1)
    return MultibaseConfig.from_file(CONFIG_PATH)


@app.command()
def init(
    name: str = typer.Argument("my-project", help="First project name (and config name)"),
    port_base: int = typer.Option(DEFAULT_PORT_BASE, "--port-base", "-p", help="Base port for the first project"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing multibase.yaml"),
):
    """Initialize a new multibase project with an example config."""
    if CONFIG_PATH.exists() and not force:
        typer.echo(f"⚠️  {CONFIG_PATH} already exists. Use --force to overwrite.")
        raise typer.Exit(1)

    cfg = MultibaseConfig.default(name, port_base)

    # Add example docs to the file
    comment = """# multibase configuration
# Add more projects under `projects:` with unique port_base values.
# Example:
# projects:
#   - name: watch_now
#     port_base: 55320
#   - name: tinideas
#     port_base: 54330
"""
    config_text = comment + "# --- generated ---\n" + cfg.to_yaml()
    CONFIG_PATH.write_text(config_text)
    typer.echo(f"✅ Created {CONFIG_PATH}")
    typer.echo(f"   Run `multibase up` to start all services.")
    typer.echo(f"   Run `multibase add <name> --port-base <port>` to add projects.")


@app.command()
def add(
    name: str = typer.Argument(..., help="Project name (e.g. 'watch-now')"),
    port_base: int = typer.Option(..., "--port-base", "-p", help="Unique base port for this project"),
):
    """Add a new Supabase project to the config."""
    cfg = _load_config()

    if any(p.name == name for p in cfg.projects):
        typer.echo(f"⚠️  Project {name!r} already exists.")
        raise typer.Exit(1)
    if any(p.port_base == port_base for p in cfg.projects):
        typer.echo(f"⚠️  Port base {port_base} already in use by another project.")
        raise typer.Exit(1)

    cfg.projects.append(ProjectConfig(name=name, port_base=port_base))
    cfg.save(CONFIG_PATH)
    typer.echo(f"✅ Added project {name!r} (base port: {port_base})")
    typer.echo(f"   Run `multibase up` to start it.")


@app.command()
def remove(
    name: str = typer.Argument(..., help="Project name to remove"),
    keep_volumes: bool = typer.Option(False, "--keep-volumes", "-k", help="Don't remove project volumes"),
):
    """Remove a project from the config."""
    cfg = _load_config()
    before = len(cfg.projects)
    cfg.projects = [p for p in cfg.projects if p.name != name]
    if len(cfg.projects) == before:
        typer.echo(f"⚠️  Project {name!r} not found.")
        raise typer.Exit(1)

    cfg.save(CONFIG_PATH)
    typer.echo(f"✅ Removed project {name!r} from config.")
    if not keep_volumes:
        typer.echo("   Note: volumes contain data. Use `docker volume rm multibase_*` to clean up.")
    typer.echo("   Run `multibase up` to apply the change.")


@app.command()
def up(
    detach: bool = typer.Option(True, "--detach/--foreground", "-d/-f", help="Run in background"),
):
    """Start all shared and per-project services."""
    cfg = _load_config()
    if not cfg.projects:
        typer.echo("⚠️  No projects configured. Use `multibase add <name> -p <port>` first.")
        raise typer.Exit(1)

    typer.echo(f"🚀 Starting {len(cfg.projects)} project(s) with multibase...")
    for p in cfg.projects:
        typer.echo(f"   · {p.name} → base port {p.port_base}")

    rc = orchestrator.up(cfg, detach=detach)
    if rc == 0:
        typer.echo("✅ All services started.")
        _print_access(cfg)
    else:
        typer.echo(f"❌ Failed with exit code {rc}", err=True)
    raise typer.Exit(rc)


@app.command()
def down(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes too (destroys data!)"),
):
    """Stop all services."""
    cfg = _load_config()
    typer.echo("🛑 Stopping all services...")
    rc = orchestrator.down(cfg, volumes=volumes)
    if rc == 0:
        typer.echo("✅ Stopped.")
    else:
        typer.echo(f"❌ Failed with exit code {rc}", err=True)
    raise typer.Exit(rc)


@app.command()
def ps():
    """Show running containers for this cluster."""
    cfg = _load_config()
    rc = orchestrator.ps(cfg)
    raise typer.Exit(rc)


@app.command()
def show():
    """Show the resolved docker-compose configuration."""
    cfg = _load_config()
    rc = orchestrator.config(cfg)
    raise typer.Exit(rc)


@app.command()
def ports():
    """Show port mapping for all configured projects."""
    cfg = _load_config()
    typer.echo("📡 multibase port mapping")
    typer.echo("")

    for proj in cfg.projects:
        base = proj.port_base
        typer.echo(f"📁 {proj.name} (base: {base})")
        typer.echo(f"     Kong API Gateway:  {base + orchestrator.KONG_OFFSET}")
        typer.echo(f"     Auth (GoTrue):    {base + orchestrator.AUTH_OFFSET}")
        typer.echo(f"     REST (PostgREST): {base + orchestrator.REST_OFFSET}")
        typer.echo(f"     Studio (internal): {base + orchestrator.STUDIO_OFFSET}")
        typer.echo(f"     Inbucket (email): {base + orchestrator.INBUCKET_OFFSET}")
        typer.echo(f"     Functions (Edge): {base + orchestrator.FUNCTIONS_OFFSET}")
        typer.echo("")

    typer.echo(f"🔧 Shared services:")
    typer.echo(f"     Studio UI:         {cfg.shared.studio_port}")
    typer.echo(f"     Kong admin:       {cfg.shared.kong_port + 1}")
    typer.echo(f"     Postgres:         5432 (internal)")
    typer.echo("")


def _print_access(cfg: MultibaseConfig) -> None:
    """Print access URLs for all projects."""
    typer.echo("")
    typer.echo("📡 Access URLs:")
    ip = _get_tailscale_ip()
    studio_port = cfg.shared.studio_port

    for proj in cfg.projects:
        base = proj.port_base
        api_port = base + orchestrator.KONG_OFFSET
        studio_url = f"http://localhost:{studio_port}?project={proj.name}"
        if ip:
            studio_url += f" | http://{ip}:{studio_port}?project={proj.name}"

        typer.echo(f"   {proj.name}:")
        typer.echo(f"     API:    http://localhost:{api_port}")
        typer.echo(f"     Studio: {studio_url}")
        if ip:
            typer.echo(f"     API:    http://{ip}:{api_port}")

    typer.echo("")


def _get_tailscale_ip() -> str | None:
    try:
        import subprocess
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


@app.command()
def mcp(
    transport: str = typer.Option("stdio", "--transport", "-t", help="Transport: stdio or http"),
    host: str = typer.Option("0.0.0.0", "--host", help="HTTP host (only for --transport http)"),
    port: int = typer.Option(8085, "--port", "-p", help="HTTP port (only for --transport http)"),
):
    """Start the multibase MCP server (for AI agent control).

    stdio mode: pipe to/from an AI agent (Claude Code, Hermes, etc.)
    http mode:  remote control via REST/MCP over HTTP
    """
    from multibase.mcp_server import serve_stdio, serve_http

    if transport == "stdio":
        typer.echo("🧠 multibase MCP server (stdio) — waiting for AI agent...", err=True)
        serve_stdio()
    elif transport == "http":
        typer.echo(f"🧠 multibase MCP server (HTTP) — listening on http://{host}:{port}", err=True)
        serve_http(host=host, port=port)
    else:
        typer.echo(f"❌ Unknown transport: {transport}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
