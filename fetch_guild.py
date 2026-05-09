"""
Fetch guild + per-player roster from swgoh.gg public API.
Caches each player JSON under cache/players/{ally_code}.json.

Usage:
    python fetch_guild.py            # uses config.yaml
    python fetch_guild.py --force    # ignore cache, refetch all
"""
import argparse
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Windows cp950 console can't print arbitrary Unicode (player names with rare chars)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

try:
    import yaml
except ImportError:
    print("Missing PyYAML. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
PLAYER_DIR = CACHE_DIR / "players"
GUILD_PATH = CACHE_DIR / "guild.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
API_BASE = "https://swgoh.gg/api"

CURL = shutil.which("curl") or "curl"

# Prefer curl_cffi (browser TLS fingerprint, bypasses Cloudflare on cloud IPs).
# Fallback to subprocess curl (sufficient on residential IPs).
try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False


def _get_via_cffi(url: str) -> dict:
    r = cffi_requests.get(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
        impersonate="chrome",
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _get_via_curl(url: str) -> dict:
    result = subprocess.run(
        [CURL, "-s", "-S", "--fail",
         "-H", f"User-Agent: {UA}",
         "-H", "Accept: application/json",
         "--max-time", "30",
         url],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode}: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def http_get_json(url: str, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            if _HAS_CFFI:
                return _get_via_cffi(url)
            return _get_via_curl(url)
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"GET failed: {url} ({last_err})")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_guild(guild_id: str) -> dict:
    print(f"[guild] {guild_id}")
    return http_get_json(f"{API_BASE}/guild-profile/{guild_id}/")


def cache_age_hours(path: Path) -> float:
    if not path.exists():
        return float("inf")
    return (time.time() - path.stat().st_mtime) / 3600


def fetch_player(ally_code: int, ttl_hours: float, force: bool) -> dict:
    out = PLAYER_DIR / f"{ally_code}.json"
    if not force and cache_age_hours(out) < ttl_hours:
        with open(out, encoding="utf-8") as f:
            return json.load(f)
    data = http_get_json(f"{API_BASE}/player/{ally_code}/")
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Ignore cache, refetch all")
    args = parser.parse_args()

    cfg = load_config()
    PLAYER_DIR.mkdir(parents=True, exist_ok=True)

    guild = fetch_guild(cfg["guild_id"])
    GUILD_PATH.write_text(json.dumps(guild, ensure_ascii=False), encoding="utf-8")
    members = guild["data"]["members"]
    print(f"[guild] {guild['data']['name']} — {len(members)} members")

    ttl = float(cfg.get("cache_ttl_hours", 6))
    fetched = cached = 0
    for i, m in enumerate(members, 1):
        ally = m["ally_code"]
        path = PLAYER_DIR / f"{ally}.json"
        is_cached = not args.force and cache_age_hours(path) < ttl
        try:
            fetch_player(ally, ttl, args.force)
        except Exception as e:
            print(f"  [{i}/{len(members)}] {m['player_name']:>20s}  FAIL: {e}")
            continue
        if is_cached:
            cached += 1
            tag = "cache"
        else:
            fetched += 1
            tag = "fetch"
            time.sleep(0.5)  # be polite to the API
        print(f"  [{i}/{len(members)}] {m['player_name']:>20s}  [{tag}]")

    print(f"\nDone. fetched={fetched} cached={cached}")


if __name__ == "__main__":
    main()
