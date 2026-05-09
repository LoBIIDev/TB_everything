"""
Generate a Line-friendly text snippet listing only Operation deficits
(in 繁中) for posting to the guild chat.

Output:
  - Prints to stdout for copy-paste
  - Also writes to line_message.txt

Usage:
    python line_message.py
"""
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYER_DIR = ROOT / "cache" / "players"
GUILD_PATH = ROOT / "cache" / "guild.json"
REQ_PATH = ROOT / "requirements.json"
ALIAS_PATH = ROOT / "unit_alias.json"  # 簡稱 (preferred)
ZH_PATH = ROOT / "unit_zh.json"        # 全名繁中 (fallback)
OUT_PATH = ROOT / "docs" / "line_message.txt"

RELIC_OFFSET = 2
WEB_URL = "https://lobiidev.github.io/TB_everything/"


def normalize(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", ascii_str.lower())


def _load_aliases(*paths):
    """Merge alias maps in order; later paths override earlier ones."""
    merged = {}
    for p in paths:
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for k, v in d.items():
            if k.startswith("_") or not v:
                continue
            merged[k] = v
    return merged


def load():
    if not GUILD_PATH.exists():
        sys.exit("guild.json missing — run fetch_guild.py first")
    return (
        json.loads(GUILD_PATH.read_text(encoding="utf-8")),
        json.loads(REQ_PATH.read_text(encoding="utf-8")),
        _load_aliases(ZH_PATH, ALIAS_PATH),  # alias overrides zh
    )


def collect_owners(members, target_keys):
    owners = {k: [] for k in target_keys}
    for m in members:
        path = PLAYER_DIR / f"{m['ally_code']}.json"
        if not path.exists():
            continue
        player = json.loads(path.read_text(encoding="utf-8"))
        for u in player.get("units", []):
            d = u.get("data", {})
            key = normalize(d.get("name", ""))
            if key not in target_keys:
                continue
            owners[key].append({
                "rarity": d.get("rarity") or 0,
                "relic_tier": d.get("relic_tier") or 0,
                "combat_type": d.get("combat_type") or 0,
            })
    return owners


def build_combined_deficits(requirements, owners):
    """Aggregate per-unit demand across operations; return only deficits."""
    by_key = {}
    for op in requirements["operations"]:
        for u in op["units"]:
            key = normalize(u["name"])
            entry = by_key.setdefault(key, {
                "name": u["name"],
                "needed": 0,
                "char_min_relic": op["char_min_relic"],
                "ship_min_rarity": op["ship_min_rarity"],
            })
            entry["needed"] += u["count"]

    rows = []
    for key, e in by_key.items():
        recs = owners.get(key, [])
        ct = recs[0]["combat_type"] if recs else 0
        if ct == 2:
            eligible = sum(1 for r in recs if r["rarity"] >= e["ship_min_rarity"])
        else:
            api_thr = e["char_min_relic"] + RELIC_OFFSET
            eligible = sum(1 for r in recs if r["relic_tier"] >= api_thr)
        deficit = max(0, e["needed"] - eligible)
        if deficit > 0:
            rows.append({"name": e["name"], "deficit": deficit,
                         "needed": e["needed"], "eligible": eligible,
                         "combat_type": ct})
    rows.sort(key=lambda r: (-r["deficit"], -r["needed"], r["name"]))
    return rows


def format_message(guild, rows, zh_map):
    today = datetime.now().strftime("%Y-%m-%d")
    name = guild["data"]["name"]
    total_deficit = sum(r["deficit"] for r in rows)
    total_need = 180  # known: Vandor 90 + Kafrene 90

    lines = [
        f"【{name}】Vandor + Kafrene Operation 缺口",
        f"更新：{today}　|　總缺口 {total_deficit} 隻 R9 角色",
        "",
    ]

    # Group by deficit count
    groups = {}
    for r in rows:
        groups.setdefault(r["deficit"], []).append(r)

    for d in sorted(groups.keys(), reverse=True):
        units = groups[d]
        lines.append(f"▍缺 {d}（{len(units)} 隻角色）")
        for u in units:
            zh = zh_map.get(u["name"], u["name"])
            tag = "🚢" if u["combat_type"] == 2 else ""
            lines.append(f"・{zh}{tag} -{d}")
        lines.append("")

    lines.append(f"📊 詳細：{WEB_URL}")
    return "\n".join(lines).rstrip() + "\n"


def main():
    guild, requirements, zh_map = load()
    target_keys = {normalize(u["name"]) for op in requirements["operations"] for u in op["units"]}
    owners = collect_owners(guild["data"]["members"], target_keys)
    rows = build_combined_deficits(requirements, owners)
    msg = format_message(guild, rows, zh_map)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(msg, encoding="utf-8")
    print(msg)
    print(f"\n[saved to {OUT_PATH}, {OUT_PATH.stat().st_size} bytes]", file=sys.stderr)


if __name__ == "__main__":
    main()
