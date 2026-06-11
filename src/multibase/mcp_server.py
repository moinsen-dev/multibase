"""
MCP server for multibase — lets AI agents (Claude, Hermes, etc.)
manage Supabase projects through standardized tools.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from multibase import orchestrator
from multibase.config import MultibaseConfig, ProjectConfig
from multibase.kong_config import generate_kong_yaml

# ── MCP Protocol helpers ──────────────────────────────


def jsonrpc_response(id: int | None, result: Any = None, error: dict | None = None) -> str:
    msg: dict[str, Any] = {"jsonrpc": "2.0"}
    if id is not None:
        msg["id"] = id
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    return json.dumps(msg)


def jsonrpc_error(id: int | None, code: int, message: str, data: Any = None) -> str:
    err: dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    return jsonrpc_response(id, error=err)


# ── Tool registry ─────────────────────────────────────


def handle_list_tools(id: int | None) -> str:
    tools = [
        {
            "name": "multibase_init",
            "description": "Initialize a new multibase project with a config file",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "First project name"},
                    "port_base": {"type": "integer", "description": "Base port for the project (default: 54320)"},
                    "path": {"type": "string", "description": "Working directory (default: current)"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "multibase_add_project",
            "description": "Add a new Supabase project to an existing multibase cluster",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name (e.g. 'watch-now')"},
                    "port_base": {"type": "integer", "description": "Unique base port (e.g. 55320)"},
                    "path": {"type": "string", "description": "Working directory"},
                },
                "required": ["name", "port_base"],
            },
        },
        {
            "name": "multibase_remove_project",
            "description": "Remove a project from the multibase config (does NOT delete volumes)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name to remove"},
                    "path": {"type": "string", "description": "Working directory"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "multibase_up",
            "description": "Start all shared and per-project services",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory with multibase.yaml"},
                },
            },
        },
        {
            "name": "multibase_down",
            "description": "Stop all services (optionally remove volumes)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "volumes": {"type": "boolean", "description": "Remove volumes too (destroys data!)"},
                    "path": {"type": "string", "description": "Working directory"},
                },
            },
        },
        {
            "name": "multibase_status",
            "description": "Show running containers and port mapping",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory"},
                },
            },
        },
        {
            "name": "multibase_list_projects",
            "description": "List all configured projects with their port mappings",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory"},
                },
            },
        },
        {
            "name": "multibase_show_config",
            "description": "Show the full resolved docker-compose configuration",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory"},
                },
            },
        },
        {
            "name": "multibase_show_kong_config",
            "description": "Show the generated Kong declarative config",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory"},
                },
            },
        },
    ]
    return jsonrpc_response(id, {"tools": tools})


def _resolve_path(path: str | None) -> Path:
    if path:
        return Path(path).resolve()
    return Path.cwd()


def _load_config(wd: Path) -> MultibaseConfig:
    config_path = wd / "multibase.yaml"
    if not config_path.exists():
        return MultibaseConfig(name=wd.name)
    return MultibaseConfig.from_file(config_path)


def handle_tool_call(id: int | None, name: str, args: dict) -> str:
    wd = _resolve_path(args.pop("path", None))

    try:
        if name == "multibase_init":
            return _cmd_init(id, args, wd)
        elif name == "multibase_add_project":
            return _cmd_add(id, args, wd)
        elif name == "multibase_remove_project":
            return _cmd_remove(id, args, wd)
        elif name == "multibase_up":
            return _cmd_up(id, wd)
        elif name == "multibase_down":
            return _cmd_down(id, args, wd)
        elif name == "multibase_status":
            return _cmd_status(id, wd)
        elif name == "multibase_list_projects":
            return _cmd_list(id, wd)
        elif name == "multibase_show_config":
            return _cmd_show_config(id, wd)
        elif name == "multibase_show_kong_config":
            return _cmd_kong_config(id, wd)
        else:
            return jsonrpc_error(id, -32601, f"Unknown tool: {name}")
    except Exception as e:
        return jsonrpc_error(id, -32603, str(e))


def _cmd_init(id: int | None, args: dict, wd: Path) -> str:
    name = args["name"]
    port_base = args.get("port_base", 54320)
    cfg = MultibaseConfig.default(name, port_base)
    cfg_path = wd / "multibase.yaml"
    cfg.save(cfg_path)
    return jsonrpc_response(id, {
        "status": "created",
        "path": str(cfg_path),
        "projects": [p.model_dump(mode="python") for p in cfg.projects],
    })


def _cmd_add(id: int | None, args: dict, wd: Path) -> str:
    name = args["name"]
    port_base = int(args["port_base"])
    cfg = _load_config(wd)

    if any(p.name == name for p in cfg.projects):
        return jsonrpc_error(id, -32602, f"Project {name!r} already exists")

    proj = ProjectConfig(name=name, port_base=port_base)
    cfg.projects.append(proj)
    cfg.save(wd / "multibase.yaml")

    return jsonrpc_response(id, {
        "status": "added",
        "project": proj.model_dump(mode="python"),
    })


def _cmd_remove(id: int | None, args: dict, wd: Path) -> str:
    name = args["name"]
    cfg = _load_config(wd)
    old_len = len(cfg.projects)
    cfg.projects = [p for p in cfg.projects if p.name != name]

    if len(cfg.projects) == old_len:
        return jsonrpc_error(id, -32602, f"Project {name!r} not found")

    cfg.save(wd / "multibase.yaml")
    return jsonrpc_response(id, {
        "status": "removed",
        "project": name,
    })


def _cmd_up(id: int | None, wd: Path) -> str:
    cfg = _load_config(wd)
    if not cfg.projects:
        return jsonrpc_error(id, -32602, "No projects configured")

    # Save Kong config alongside compose
    kong_path = wd / "kong.yml"
    save_kong_yaml(cfg, str(kong_path))

    rc = orchestrator.up(cfg, detach=True)
    if rc != 0:
        return jsonrpc_error(id, -32603, f"Docker compose failed with exit code {rc}")

    # Collect info
    projects_info = []
    for proj in cfg.projects:
        base = proj.port_base
        projects_info.append({
            "name": proj.name,
            "port_base": base,
            "api_url": f"http://localhost:{base + orchestrator.KONG_OFFSET}",
            "studio_url": f"http://localhost:{cfg.shared.studio_port}?project={proj.name}",
        })

    return jsonrpc_response(id, {
        "status": "started",
        "projects": projects_info,
    })


def _cmd_down(id: int | None, args: dict, wd: Path) -> str:
    cfg = _load_config(wd)
    remove_volumes = args.get("volumes", False)
    rc = orchestrator.down(cfg, volumes=remove_volumes)
    if rc != 0:
        return jsonrpc_error(id, -32603, f"Docker compose failed with exit code {rc}")
    return jsonrpc_response(id, {"status": "stopped"})


def _cmd_status(id: int | None, wd: Path) -> str:
    cfg = _load_config(wd)

    # Get running containers via docker ps
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name=multibase_{cfg.name}",
             "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t", 3)
                containers.append({
                    "name": parts[0] if len(parts) > 0 else "",
                    "image": parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                    "ports": parts[3] if len(parts) > 3 else "",
                })

        total_ram = _get_container_ram(cfg)
    except Exception:
        containers = []
        total_ram = "unknown"

    return jsonrpc_response(id, {
        "project_count": len(cfg.projects),
        "running_containers": len(containers),
        "containers": containers,
        "total_ram": total_ram,
    })


def _cmd_list(id: int | None, wd: Path) -> str:
    cfg = _load_config(wd)
    projects = []
    for proj in cfg.projects:
        projects.append({
            "name": proj.name,
            "port_base": proj.port_base,
            "ports": {
                "kong": proj.port_base + orchestrator.KONG_OFFSET,
                "auth": proj.port_base + orchestrator.AUTH_OFFSET,
                "rest": proj.port_base + orchestrator.REST_OFFSET,
                "inbucket": proj.port_base + orchestrator.INBUCKET_OFFSET,
                "functions": proj.port_base + orchestrator.FUNCTIONS_OFFSET,
            },
        })

    return jsonrpc_response(id, {
        "name": cfg.name,
        "shared": cfg.shared.model_dump(mode="python"),
        "projects": projects,
    })


def _cmd_show_config(id: int | None, wd: Path) -> str:
    cfg = _load_config(wd)
    compose = orchestrator.generate_compose(cfg)
    return jsonrpc_response(id, {
        "compose": yaml.dump(compose, default_flow_style=False),
    })


def _cmd_kong_config(id: int | None, wd: Path) -> str:
    cfg = _load_config(wd)
    kong_yaml = generate_kong_yaml(cfg)
    return jsonrpc_response(id, {
        "kong_yaml": kong_yaml,
    })


def _get_container_ram(cfg: MultibaseConfig) -> str:
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream",
             "--filter", f"name=multibase_{cfg.name}",
             "--format", "{{.Name}} {{.MemUsage}}"],
            capture_output=True, text=True, timeout=10,
        )
        total_mb = 0.0
        for line in result.stdout.strip().split("\n"):
            if line and "/" in line:
                mem_part = line.split()[-2] if len(line.split()) >= 2 else "0MiB"
                if "MiB" in mem_part:
                    total_mb += float(mem_part.replace("MiB", ""))
                elif "GiB" in mem_part:
                    total_mb += float(mem_part.replace("GiB", "")) * 1024
        if total_mb > 1024:
            return f"{total_mb / 1024:.1f} GiB"
        return f"{total_mb:.0f} MiB"
    except Exception:
        return "unknown"


def save_kong_yaml(cfg: MultibaseConfig, out_path: str) -> None:
    content = generate_kong_yaml(cfg)
    Path(out_path).write_text(content)


# ── MCP Server loop ──────────────────────────────────


def serve_stdio() -> None:
    """Run the MCP server over stdio (for local AI agent integration)."""
    # Send capabilities
    print(jsonrpc_response(None, {
        "protocolVersion": "2025-03-26",
        "serverInfo": {"name": "multibase-mcp", "version": "0.2.0"},
        "capabilities": {
            "tools": {},
        },
    }))
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(jsonrpc_error(None, -32700, "Parse error"))
            sys.stdout.flush()
            continue

        msg_id = msg.get("id")
        method = msg.get("method")

        if method == "tools/list":
            print(handle_list_tools(msg_id))
        elif method == "tools/call":
            print(handle_tool_call(msg_id, msg["params"]["name"], msg["params"].get("arguments", {})))
        elif method == "initialize":
            print(jsonrpc_response(msg_id, {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "multibase-mcp", "version": "0.2.0"},
                "capabilities": {"tools": {}},
            }))
        elif method == "notifications/initialized":
            pass  # no response expected
        elif method == "shutdown":
            print(jsonrpc_response(msg_id, None))
            break
        else:
            print(jsonrpc_error(msg_id, -32601, f"Unknown method: {method}"))

        sys.stdout.flush()


def serve_http(host: str = "0.0.0.0", port: int = 8085) -> None:
    """Run the MCP server over HTTP/SSE for remote access."""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class MCPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode() if content_length else "{}"

            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                self._respond(400, jsonrpc_error(None, -32700, "Parse error"))
                return

            msg_id = msg.get("id")
            method = msg.get("method")

            if method == "tools/list":
                response = handle_list_tools(msg_id)
            elif method == "tools/call":
                response = handle_tool_call(
                    msg_id,
                    msg["params"]["name"],
                    msg["params"].get("arguments", {}),
                )
            elif method == "initialize":
                response = jsonrpc_response(msg_id, {
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {"name": "multibase-mcp", "version": "0.2.0"},
                    "capabilities": {"tools": {}},
                })
            elif method == "shutdown":
                response = jsonrpc_response(msg_id, None)
                self._respond(200, response)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                response = jsonrpc_error(msg_id, -32601, f"Unknown method: {method}")

            self._respond(200, response)

        def _respond(self, status: int, body: str):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, fmt, *args):
            pass  # quieter

    import threading
    server = HTTPServer((host, port), MCPHandler)
    print(f"multibase MCP server listening on http://{host}:{port}", file=sys.stderr)
    print(jsonrpc_response(None, {
        "status": "running",
        "endpoint": f"http://{host}:{port}",
    }))
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)


if __name__ == "__main__":
    serve_stdio()
