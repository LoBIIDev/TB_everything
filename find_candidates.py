"""
For each unit with a deficit (eligible < needed), list the guild members
who already own the unit, sorted by closest-to-threshold first.

Helps the guild lead identify whose Ima-Gun Di/Omega/etc. is closest to R9.

Usage:
    python find_candidates.py
    python find_candidates.py --top 10        # show top 10 owners per unit
    python find_candidates.py --include-met   # also show units that already meet threshold
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYER_DIR = ROOT / "cache" / "players"
GUILD_PATH = ROOT / "cache" / "guild.json"
REQ_PATH = ROOT / "requirements.json"

# swgoh.gg API stores relic_tier offset by +2 from in-game level
RELIC_OFFSET = 2


def normalize(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", ascii_str.lower())


def load_all():
    if not GUILD_PATH.exists():
        sys.exit("guild.json not found — run fetch_guild.py first")
    guild = json.loads(GUILD_PATH.read_text(encoding="utf-8"))
    requirements = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    return guild, requirements


def collect_owners(members: list, target_keys: set) -> dict:
    """For each normalized name in target_keys, gather list of owner records."""
    owners = {k: [] for k in target_keys}
    name_lookup = {}
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
            name_lookup.setdefault(key, d.get("name"))
            owners[key].append({
                "player": m["player_name"],
                "level": d.get("level") or 0,
                "rarity": d.get("rarity") or 0,
                "gear_level": d.get("gear_level") or 0,
                "relic_tier": d.get("relic_tier") or 0,
                "power": d.get("power") or 0,
                "combat_type": d.get("combat_type") or 0,
            })
    return owners, name_lookup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=8, help="Top N candidates per unit (default 8)")
    parser.add_argument("--include-met", action="store_true",
                        help="Also list units that already meet threshold")
    args = parser.parse_args()

    guild, requirements = load_all()
    members = guild["data"]["members"]

    # Combined demand: aggregate per unit across all operations (same phase, shared pool)
    target_keys = set()
    by_key = {}
    for op in requirements["operations"]:
        for u in op["units"]:
            key = normalize(u["name"])
            target_keys.add(key)
            entry = by_key.setdefault(key, {
                "key": key,
                "name": u["name"],
                "needed": 0,
                "ops": [],
                "char_min_relic": op["char_min_relic"],
                "ship_min_rarity": op["ship_min_rarity"],
            })
            entry["needed"] += u["count"]
            entry["ops"].append(f"{op['name']}×{u['count']}")
    per_op_units = sorted(by_key.values(), key=lambda x: -x["needed"])

    owners, name_lookup = collect_owners(members, target_keys)

    print(f"\nGuild: {guild['data']['name']}  |  Members: {len(members)}\n")

    shown_any = False
    for u in per_op_units:
        recs = owners.get(u["key"], [])
        ct = recs[0]["combat_type"] if recs else 0
        if ct == 1 or (ct == 0 and "Profundity" not in u["name"] and "Scythe" not in u["name"]):
            # Treat unknown as char by default
            threshold = u["char_min_relic"]                       # game-level
            api_threshold = threshold + RELIC_OFFSET              # API-level
            eligible = sum(1 for r in recs if r["relic_tier"] >= api_threshold)
            metric_label = "R"
            metric_key = "relic_tier"
            shown_threshold = threshold
            shown_offset = RELIC_OFFSET
        else:
            threshold = u["ship_min_rarity"]
            api_threshold = threshold
            eligible = sum(1 for r in recs if r["rarity"] >= api_threshold)
            metric_label = "*"
            metric_key = "rarity"
            shown_threshold = threshold
            shown_offset = 0

        deficit = max(0, u["needed"] - eligible)
        if deficit == 0 and not args.include_met:
            continue
        shown_any = True

        # Sort: those NOT yet at threshold by metric desc (closest first), then power desc
        below = [r for r in recs if r[metric_key] < api_threshold]
        below.sort(key=lambda r: (-r[metric_key], -r["power"]))
        ready = sum(1 for r in recs if r[metric_key] >= api_threshold)

        ops_str = " + ".join(u["ops"])
        print(f"━━━ {u['name']}  "
              f"(need {u['needed']}, have {ready} at {metric_label}{shown_threshold}+, deficit {deficit})  [{ops_str}]")

        if not below:
            print("   (no one below threshold owns this unit)")
            print()
            continue

        for r in below[:args.top]:
            extras = []
            if ct == 1:
                extras.append(f"G{r['gear_level']}")
                extras.append(f"{r['rarity']}*")
                extras.append(f"L{r['level']}")
            else:
                extras.append(f"L{r['level']}")
            extras.append(f"P{r['power']:,}")
            display_metric = r[metric_key] - shown_offset if ct == 1 else r[metric_key]
            print(f"   {metric_label}{display_metric:<2d}  {r['player']:<22s}  {' '.join(extras)}")
        if len(below) > args.top:
            print(f"   …{len(below) - args.top} more below threshold")
        print()

    if not shown_any:
        print("All Operation requirements are already met — no candidates needed.\n")


if __name__ == "__main__":
    main()
