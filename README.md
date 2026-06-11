# multibase 🏗️

> **Run multiple Supabase projects on one host — share the heavy services, keep projects isolated.**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)

Running several Supabase projects locally? Each `supabase start` spins up a **full stack** — Postgres, Kong, Studio, Realtime, Logflare, Storage, Auth, Rest, Inbucket, Edge Runtime, Vector... **10+ containers per project**.

With 3 projects that's **30+ containers** and **~4.4 GB RAM**.

**multibase** shares the infrastructure services and runs only the project-specific parts per project. Same isolated databases, same Supabase CLI compatibility — but half the RAM.

## How it works

```
Without multibase:
  Project A ── 10 containers ──┐
  Project B ── 10 containers ──┤  30 containers
  Project C ── 10 containers ──┘  ~4.4 GB RAM

With multibase:
  ┌─ Shared ──────────────────┐
  │  Postgres (3 databases)    │
  │  Kong (API gateway)        │
  │  Studio (1 instance)       │
  │  Realtime (1 instance)     │
  │  Logflare (1 instance)     │
  │  Storage (1 instance)      │
  └────────────────────────────┘
  ┌─ Per project ─────────────┐
  │  GoTrue (Auth)            │
  │  PostgREST (REST API)     │
  │  Edge Runtime (Functions) │
  │  Inbucket (Email)         │
  └────────────────────────────┘
  ≈ 15 containers, ~2.0 GB RAM
```

## Installation

```bash
pip install multibase
```

Or from source:
```bash
git clone https://github.com/moinsen-dev/multibase.git
cd multibase
pip install -e .
```

## Quick start

```bash
# 1. Init a project
multibase init my-project --port-base 54320

# 2. Edit multibase.yaml to add more projects
#    (or use `multibase add`)

# 3. Start everything
multibase up

# 4. Check running services
multibase ps

# 5. See port mapping
multibase ports

# 6. Stop
multibase down
```

## Add a project

```bash
multibase add watch-now --port-base 55320
multibase up  # starts only the new project's services
```

## Port allocation

Each project gets a **port base** — all services are `base + offset`:

| Service  | Offset | Example (base 54320) |
|----------|--------|---------------------|
| Kong     | +1     | 54321               |
| Auth     | +2     | 54322               |
| REST     | +3     | 54323               |
| Studio   | +4     | 54324               |
| Inbucket | +5     | 54325               |
| Edge Runtime | +6 | 54326               |

## Remote access (with Tailscale)

multibase auto-detects your Tailscale IP and prints remote URLs:

```bash
$ multibase up
📡 Access URLs:
   tinideas:
     API:    http://localhost:54331
     Studio: http://localhost:3000?project=tinideas | http://100.64.0.1:3000?project=tinideas
```

## Requirements

- Docker / OrbStack
- Python 3.10+
- Optional: Tailscale for remote access

## License

MIT — see [LICENSE](LICENSE).

## Contributing

PRs welcome! The project is in early alpha — lots of room for improvement:

- [ ] Kong declarative config generation with per-project routes
- [ ] `multibase db create` to initialize per-project databases
- [ ] Auto-migration of supabase CLI projects
- [ ] Per-project JWT secret generation
- [ ] CLI completions
- [ ] Tests
