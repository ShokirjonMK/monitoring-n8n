"""
monitor-agent — host nazorat agenti.

Bitta server haqida JSON ko'rinishida ma'lumot beradi: containerlar, resurslar,
proyekt endpointlari, ma'lumotlar bazalari, SSL sertifikatlar, backuplar.

Auth: Bearer token (`AGENT_TOKEN` env yoki /run/secrets/agent_token).
Config: /app/config.yml (volume orqali).

Barcha buyruqlar mezbon (host) namespace'ida bajariladi:
  - docker — `/var/run/docker.sock` mount
  - df/free/uptime — `/host` mount (ro)
  - pg_dump — host'dagi container ichida (`docker exec`) yoki agent ichida client orqali
"""
from __future__ import annotations

import os
import re
import ssl
import json
import time
import socket
import shutil
import secrets
import logging
import asyncio
import datetime
import subprocess
from pathlib import Path
from typing import Any

import yaml
import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse

# ─── Setup ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("agent")

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/app/config.yml"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def _load_token() -> str:
    """Token order: file (Docker secret) > env > ephemeral."""
    file_path = os.getenv("AGENT_TOKEN_FILE")
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text().strip()
    if os.getenv("AGENT_TOKEN"):
        return os.environ["AGENT_TOKEN"].strip()
    tok = secrets.token_urlsafe(32)
    log.warning(f"AGENT_TOKEN not set — generated ephemeral: {tok}")
    return tok


AGENT_TOKEN = _load_token()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.warning(f"{CONFIG_PATH} missing — using empty defaults")
        return {
            "server_name": socket.gethostname(),
            "endpoints": [],
            "databases": [],
            "backups": [],
            "domains": [],
            "thresholds": {"disk_pct": 80, "mem_pct": 85, "load_1m": 5},
        }
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


CONFIG = load_config()

app = FastAPI(title="monitor-agent", docs_url=None, redoc_url=None, openapi_url=None)


# ─── Auth ─────────────────────────────────────────────────────────────────────

def auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if not secrets.compare_digest(authorization.removeprefix("Bearer ").strip(), AGENT_TOKEN):
        raise HTTPException(401, "invalid token")


# ─── Subprocess helper ────────────────────────────────────────────────────────

def run(cmd: list[str], timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
    """Run a command. Returns (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=check,
            stdin=subprocess.DEVNULL,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", f"not found: {e}"


# ─── Containers ───────────────────────────────────────────────────────────────

def list_containers() -> list[dict]:
    """All containers on the host. Empty list if docker is unreachable.

    Note: `--format json` (Docker ≥23 native JSON Lines) is used because the older
    `{{json .}}` template invocation hangs intermittently from Python subprocess
    (likely a buffering/locale interaction with the template engine).
    """
    code, out, err = run([
        "docker", "ps", "-a", "--format", "json",
    ])
    if code != 0:
        log.error(f"docker ps failed: {err}")
        return []
    items = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        items.append({
            "name": j.get("Names", ""),
            "image": j.get("Image", ""),
            "status": j.get("Status", ""),
            "state": j.get("State", ""),
            "health": _health_from_status(j.get("Status", "")),
            "ports": j.get("Ports", ""),
            "created": j.get("CreatedAt", ""),
            "running_for": j.get("RunningFor", ""),
        })
    return items


def _health_from_status(s: str) -> str:
    """healthy / unhealthy / starting / none / exited"""
    if "(healthy)" in s: return "healthy"
    if "(unhealthy)" in s: return "unhealthy"
    if "(health: starting)" in s: return "starting"
    if s.startswith("Up"): return "none"
    if s.startswith("Exited"): return "exited"
    if s.startswith("Restarting"): return "restarting"
    if s.startswith("Created"): return "created"
    return "unknown"


# ─── Resources ────────────────────────────────────────────────────────────────

def disk_usage() -> list[dict]:
    """`df -h` for /, /var, /opt — anything mounted under /host."""
    code, out, _ = run(["df", "-PB1", "/host"], timeout=10) if Path("/host").exists() else run(["df", "-PB1", "/"])
    if code != 0:
        return []
    lines = out.strip().split("\n")[1:]
    res = []
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            total = int(parts[1])
            used = int(parts[2])
            avail = int(parts[3])
            pct = int(parts[4].rstrip("%"))
        except ValueError:
            continue
        res.append({
            "filesystem": parts[0],
            "mount": parts[5],
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": avail,
            "used_pct": pct,
        })
    return res


def mem_info() -> dict:
    """Read /host/proc/meminfo if available, else /proc/meminfo."""
    src = Path("/host/proc/meminfo")
    if not src.exists():
        src = Path("/proc/meminfo")
    if not src.exists():
        return {}
    info = {}
    with src.open() as f:
        for line in f:
            k, _, rest = line.partition(":")
            v = rest.strip().split()[0]
            try:
                info[k] = int(v) * 1024  # kB → bytes
            except ValueError:
                pass
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    used = total - avail
    return {
        "total_bytes": total,
        "available_bytes": avail,
        "used_bytes": used,
        "used_pct": round(used / total * 100, 1) if total else 0,
        "swap_total_bytes": info.get("SwapTotal", 0),
        "swap_used_bytes": info.get("SwapTotal", 0) - info.get("SwapFree", 0),
    }


def load_avg() -> dict:
    """Read /host/proc/loadavg or /proc/loadavg."""
    src = Path("/host/proc/loadavg")
    if not src.exists():
        src = Path("/proc/loadavg")
    if not src.exists():
        return {}
    parts = src.read_text().strip().split()
    return {"1m": float(parts[0]), "5m": float(parts[1]), "15m": float(parts[2])}


def uptime_seconds() -> int:
    src = Path("/host/proc/uptime")
    if not src.exists():
        src = Path("/proc/uptime")
    if not src.exists():
        return 0
    try:
        return int(float(src.read_text().split()[0]))
    except Exception:
        return 0


# ─── Endpoint health ──────────────────────────────────────────────────────────

async def check_endpoints() -> list[dict]:
    """HTTP check each configured endpoint (concurrent)."""
    endpoints = CONFIG.get("endpoints", [])
    if not endpoints:
        return []

    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        async def probe(ep):
            url = ep["url"]
            expected = ep.get("expect", 200)
            method = ep.get("method", "GET")
            t0 = time.time()
            try:
                r = await client.request(method, url)
                ms = round((time.time() - t0) * 1000)
                ok = r.status_code == expected if isinstance(expected, int) else (r.status_code in expected)
                return {
                    "name": ep.get("name", url),
                    "url": url,
                    "status": r.status_code,
                    "expected": expected,
                    "ok": ok,
                    "elapsed_ms": ms,
                }
            except Exception as e:
                return {
                    "name": ep.get("name", url),
                    "url": url,
                    "status": None,
                    "expected": expected,
                    "ok": False,
                    "error": str(e)[:200],
                    "elapsed_ms": round((time.time() - t0) * 1000),
                }

        return await asyncio.gather(*[probe(e) for e in endpoints])


# ─── Database health ──────────────────────────────────────────────────────────

def check_databases() -> list[dict]:
    out = []
    for db in CONFIG.get("databases", []):
        name = db.get("name", "?")
        kind = db.get("type", "")
        item = {"name": name, "type": kind, "ok": False, "info": {}}

        if kind == "postgres":
            container = db.get("container")
            user = db.get("user", "postgres")
            dbname = db.get("db", "postgres")
            code, stdout, stderr = run([
                "docker", "exec", container,
                "psql", "-U", user, "-d", dbname, "-tAc",
                "SELECT 1, pg_database_size('" + dbname + "'), (SELECT count(*) FROM pg_stat_activity)",
            ], timeout=10)
            if code == 0:
                parts = stdout.strip().split("|")
                if len(parts) >= 3:
                    item["ok"] = True
                    item["info"] = {
                        "size_bytes": int(parts[1]) if parts[1].isdigit() else 0,
                        "active_connections": int(parts[2]) if parts[2].isdigit() else 0,
                    }
            else:
                item["error"] = (stderr or stdout)[:200]

        elif kind == "sqlite":
            path = db.get("path", "")
            host_path = path
            if Path("/host").exists():
                host_path = "/host" + path  # mounted via /host
            p = Path(host_path)
            if p.exists():
                item["ok"] = True
                item["info"] = {
                    "size_bytes": p.stat().st_size,
                    "modified": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            else:
                item["error"] = f"file not found: {path}"

        out.append(item)
    return out


# ─── SSL ──────────────────────────────────────────────────────────────────────

def check_ssl(host: str, port: int = 443) -> dict:
    """Open TLS, parse cert.notAfter."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert(binary_form=True)
                # Use cryptography for accurate parse
                from cryptography import x509
                from cryptography.hazmat.backends import default_backend
                c = x509.load_der_x509_certificate(cert, default_backend())
                expires = c.not_valid_after.replace(tzinfo=datetime.timezone.utc)
                now = datetime.datetime.now(tz=datetime.timezone.utc)
                days = (expires - now).days
                issuer = c.issuer.rfc4514_string()
                subject = c.subject.rfc4514_string()
                return {
                    "host": host,
                    "port": port,
                    "ok": True,
                    "expires_at": expires.isoformat(),
                    "days_left": days,
                    "issuer": issuer,
                    "subject": subject,
                }
    except Exception as e:
        return {"host": host, "port": port, "ok": False, "error": str(e)[:200]}


# ─── Backup ───────────────────────────────────────────────────────────────────

def run_backups() -> list[dict]:
    """Run all configured backups. Returns list of {name, path, size_bytes, ok, error}."""
    results = []
    today = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    for b in CONFIG.get("backups", []):
        name = b.get("name", "?")
        kind = b.get("type")
        out_file = BACKUP_DIR / f"{name}-{today}.sql.gz"

        try:
            if kind == "pg_dump":
                container = b["container"]
                user = b.get("user", "postgres")
                dbname = b.get("db", "postgres")
                # docker exec → pg_dump → gzip → file
                with out_file.open("wb") as fp:
                    p1 = subprocess.Popen(
                        ["docker", "exec", container, "pg_dump", "-U", user, dbname],
                        stdout=subprocess.PIPE,
                    )
                    p2 = subprocess.Popen(["gzip", "-c"], stdin=p1.stdout, stdout=fp)
                    p1.stdout.close()
                    rc = p2.wait(timeout=600)
                    p1.wait(timeout=600)
                    if rc != 0 or p1.returncode != 0:
                        raise RuntimeError(f"pg_dump rc={p1.returncode} gzip rc={rc}")

            elif kind == "sqlite_copy":
                src = b["path"]
                if Path("/host").exists():
                    src = "/host" + src
                if not Path(src).exists():
                    raise FileNotFoundError(src)
                # gzip the file
                tmp = out_file.with_suffix(".db.gz")
                with open(src, "rb") as fin, open(tmp, "wb") as fout:
                    p = subprocess.Popen(["gzip", "-c"], stdin=fin, stdout=fout)
                    p.wait(timeout=120)
                    if p.returncode != 0:
                        raise RuntimeError(f"gzip rc={p.returncode}")
                out_file = tmp

            elif kind == "directory":
                src = b["path"]
                if Path("/host").exists():
                    src = "/host" + src
                tar_file = BACKUP_DIR / f"{name}-{today}.tar.gz"
                code, _, err = run(["tar", "-czf", str(tar_file), "-C", str(Path(src).parent), Path(src).name], timeout=600)
                if code != 0:
                    raise RuntimeError(f"tar rc={code} {err}")
                out_file = tar_file

            else:
                raise ValueError(f"unknown backup type: {kind}")

            results.append({
                "name": name,
                "type": kind,
                "ok": True,
                "filename": out_file.name,
                "size_bytes": out_file.stat().st_size,
            })
        except Exception as e:
            log.error(f"backup {name} failed: {e}")
            results.append({
                "name": name, "type": kind, "ok": False, "error": str(e)[:300],
            })
            try:
                out_file.unlink(missing_ok=True)
            except Exception:
                pass
    return results


def cleanup_old_backups(keep_days: int = 30) -> int:
    """Delete backup files older than `keep_days`. Returns count removed."""
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for f in BACKUP_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except Exception as e:
                log.warning(f"cleanup {f}: {e}")
    return removed


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "agent": "monitor-agent", "server": CONFIG.get("server_name")}


@app.get("/status")
async def status_full(authorization: str | None = Header(None)):
    auth(authorization)
    eps = await check_endpoints()
    return {
        "server": CONFIG.get("server_name"),
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "uptime_seconds": uptime_seconds(),
        "containers": list_containers(),
        "disk": disk_usage(),
        "memory": mem_info(),
        "load": load_avg(),
        "endpoints": eps,
        "databases": check_databases(),
        "thresholds": CONFIG.get("thresholds", {}),
    }


@app.get("/containers")
def containers_only(authorization: str | None = Header(None)):
    auth(authorization)
    return {"server": CONFIG.get("server_name"), "containers": list_containers()}


@app.get("/resources")
def resources_only(authorization: str | None = Header(None)):
    auth(authorization)
    return {
        "server": CONFIG.get("server_name"),
        "disk": disk_usage(),
        "memory": mem_info(),
        "load": load_avg(),
        "uptime_seconds": uptime_seconds(),
        "thresholds": CONFIG.get("thresholds", {}),
    }


@app.get("/endpoints")
async def endpoints_only(authorization: str | None = Header(None)):
    auth(authorization)
    return {"server": CONFIG.get("server_name"), "endpoints": await check_endpoints()}


@app.get("/databases")
def databases_only(authorization: str | None = Header(None)):
    auth(authorization)
    return {"server": CONFIG.get("server_name"), "databases": check_databases()}


@app.get("/ssl")
def ssl_check(host: str = Query(...), port: int = Query(443),
              authorization: str | None = Header(None)):
    auth(authorization)
    return check_ssl(host, port)


@app.get("/ssl/all")
def ssl_check_all(authorization: str | None = Header(None)):
    auth(authorization)
    return {
        "server": CONFIG.get("server_name"),
        "domains": [check_ssl(d["host"], d.get("port", 443)) for d in CONFIG.get("domains", [])],
    }


@app.post("/backup/run")
def backup_run(authorization: str | None = Header(None)):
    auth(authorization)
    keep = int(CONFIG.get("backup_retention_days", 30))
    removed = cleanup_old_backups(keep)
    results = run_backups()
    return {
        "server": CONFIG.get("server_name"),
        "results": results,
        "cleaned_old_backups": removed,
        "ok": all(r["ok"] for r in results) if results else True,
    }


@app.get("/backup/list")
def backup_list(authorization: str | None = Header(None)):
    auth(authorization)
    files = []
    for f in sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return {"server": CONFIG.get("server_name"), "files": files}


@app.get("/backup/file/{name}")
def backup_file(name: str, authorization: str | None = Header(None)):
    auth(authorization)
    # Prevent path traversal
    if "/" in name or ".." in name:
        raise HTTPException(400, "invalid name")
    path = BACKUP_DIR / name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "not found")

    def stream():
        with path.open("rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"',
                 "Content-Length": str(path.stat().st_size)},
    )


# ─── Docker Swarm ─────────────────────────────────────────────────────────────

def swarm_info() -> dict:
    """Detect if this host is in a swarm; return swarm summary if so."""
    code, out, err = run(["docker", "info", "--format", "json"], timeout=10)
    if code != 0:
        return {"in_swarm": False, "error": err[:200]}
    try:
        info = json.loads(out)
    except Exception:
        return {"in_swarm": False, "error": "invalid docker info json"}
    swarm = info.get("Swarm") or {}
    state = swarm.get("LocalNodeState") or "inactive"
    in_swarm = state in ("active", "pending", "locked")
    return {
        "in_swarm": in_swarm,
        "state": state,
        "node_id": swarm.get("NodeID"),
        "is_manager": bool(swarm.get("ControlAvailable")),
        "managers": swarm.get("Managers"),
        "nodes": swarm.get("Nodes"),
        "cluster_id": (swarm.get("Cluster") or {}).get("ID"),
        "raft_status": (swarm.get("RaftStatus") or {}),
    }


def swarm_services() -> list[dict]:
    """List services with replicas and basic metrics. Manager only."""
    code, out, err = run(["docker", "service", "ls", "--format", "json"], timeout=15)
    if code != 0:
        return []
    services = []
    for line in out.strip().split("\n"):
        if not line: continue
        try:
            s = json.loads(line)
        except Exception:
            continue
        # Replicas: "3/3" or "3/3 (max 5 per node)"
        rep = s.get("Replicas", "")
        running = total = 0
        try:
            parts = rep.split("/", 1)
            running = int(parts[0])
            total = int(parts[1].split()[0])
        except Exception:
            pass
        services.append({
            "id": s.get("ID"),
            "name": s.get("Name"),
            "mode": s.get("Mode"),
            "replicas_running": running,
            "replicas_desired": total,
            "image": s.get("Image"),
            "ports": s.get("Ports", ""),
        })
    return services


def swarm_nodes() -> list[dict]:
    """List swarm nodes."""
    code, out, _ = run(["docker", "node", "ls", "--format", "json"], timeout=10)
    if code != 0:
        return []
    nodes = []
    for line in out.strip().split("\n"):
        if not line: continue
        try:
            n = json.loads(line)
        except Exception:
            continue
        nodes.append({
            "id": n.get("ID"),
            "hostname": n.get("Hostname"),
            "status": n.get("Status"),
            "availability": n.get("Availability"),
            "manager_status": n.get("ManagerStatus", ""),
            "engine_version": n.get("EngineVersion"),
            "self": "*" in (n.get("ID", "") or ""),
        })
    return nodes


def swarm_service_metrics(service: str) -> dict:
    """Aggregate CPU/memory across all running tasks of a service."""
    # Get tasks for the service
    code, out, _ = run([
        "docker", "service", "ps", service, "--filter", "desired-state=running",
        "--format", "{{.Name}} {{.CurrentState}}",
    ], timeout=15)
    if code != 0:
        return {"tasks": 0, "cpu_pct": 0, "mem_pct": 0}

    task_names = []
    for line in out.strip().split("\n"):
        if line.startswith(service + ".") and "Running" in line:
            task_names.append(line.split()[0])

    if not task_names:
        return {"tasks": 0, "cpu_pct": 0, "mem_pct": 0}

    # docker stats — local node only (limitation: cross-node stats need orchestration)
    code, out, _ = run([
        "docker", "stats", "--no-stream", "--format", "{{.Name}} {{.CPUPerc}} {{.MemPerc}}",
    ], timeout=15)
    if code != 0:
        return {"tasks": len(task_names), "cpu_pct": 0, "mem_pct": 0}

    cpu_total = mem_total = count = 0.0
    for line in out.strip().split("\n"):
        parts = line.split()
        if len(parts) < 3: continue
        name = parts[0]
        # match swarm task containers (docker names them <service>.<n>.<id>)
        if not any(name.startswith(t + ".") or name == t for t in task_names):
            continue
        try:
            cpu = float(parts[1].rstrip("%"))
            mem = float(parts[2].rstrip("%"))
            cpu_total += cpu
            mem_total += mem
            count += 1
        except ValueError:
            continue

    if count == 0:
        return {"tasks": len(task_names), "cpu_pct": 0, "mem_pct": 0, "note": "no local replicas"}
    return {
        "tasks": len(task_names),
        "local_replicas": int(count),
        "cpu_pct": round(cpu_total / count, 1),
        "mem_pct": round(mem_total / count, 1),
    }


def swarm_scale(service: str, replicas: int) -> dict:
    """Scale a service. Manager only. Returns success/error."""
    if replicas < 0 or replicas > 1000:
        return {"ok": False, "error": "replicas must be 0..1000"}
    code, out, err = run([
        "docker", "service", "scale", f"{service}={replicas}", "--detach",
    ], timeout=30)
    if code != 0:
        return {"ok": False, "error": (err or out)[:300]}
    return {"ok": True, "service": service, "replicas": replicas, "stdout": out[:300]}


@app.get("/swarm/info")
def swarm_info_endpoint(authorization: str | None = Header(None)):
    auth(authorization)
    return swarm_info()


@app.get("/swarm/services")
def swarm_services_endpoint(authorization: str | None = Header(None)):
    auth(authorization)
    info = swarm_info()
    if not info.get("in_swarm") or not info.get("is_manager"):
        return {"in_swarm": info.get("in_swarm"), "is_manager": info.get("is_manager"),
                "services": [], "error": "Bu node manager emas — service ro'yxatini olmaydi"}
    return {"in_swarm": True, "services": swarm_services()}


@app.get("/swarm/nodes")
def swarm_nodes_endpoint(authorization: str | None = Header(None)):
    auth(authorization)
    info = swarm_info()
    if not info.get("in_swarm") or not info.get("is_manager"):
        return {"in_swarm": info.get("in_swarm"), "is_manager": info.get("is_manager"),
                "nodes": [], "error": "Bu node manager emas — node ro'yxatini olmaydi"}
    return {"in_swarm": True, "nodes": swarm_nodes()}


@app.get("/swarm/service/{name}/metrics")
def swarm_service_metrics_endpoint(name: str, authorization: str | None = Header(None)):
    auth(authorization)
    return {"service": name, **swarm_service_metrics(name)}


@app.post("/swarm/service/{name}/scale")
def swarm_scale_endpoint(name: str, replicas: int = Query(...),
                         authorization: str | None = Header(None)):
    auth(authorization)
    info = swarm_info()
    if not info.get("is_manager"):
        return JSONResponse({"ok": False, "error": "Bu node manager emas"}, status_code=400)
    return swarm_scale(name, replicas)


@app.get("/config")
def cfg(authorization: str | None = Header(None)):
    """Echo back the loaded config (sans secrets) — useful for debugging."""
    auth(authorization)
    return CONFIG


@app.post("/reload")
def reload_config(authorization: str | None = Header(None)):
    auth(authorization)
    global CONFIG
    CONFIG = load_config()
    return {"reloaded": True, "server": CONFIG.get("server_name")}
