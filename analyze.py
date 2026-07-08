"""
Compare guild's eligible-unit pool against per-Operation requirements.

For each required unit:
  - Characters: count guild members owning it at relic_tier >= char_min_relic
  - Ships:      count guild members owning it at rarity >= ship_min_rarity

Then compute deficit per unit, per operation, and combined.

Usage:
    python analyze.py
    python analyze.py --report report.md   # also write Markdown report
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYER_DIR = ROOT / "cache" / "players"
GUILD_PATH = ROOT / "cache" / "guild.json"
REQ_PATH = ROOT / "requirements.json"

# swgoh.gg API stores relic_tier offset by +2 from in-game level:
#   game R0 (G13 only)        -> api relic_tier=2
#   game R9                   -> api relic_tier=11
RELIC_OFFSET = 2


def normalize(s: str) -> str:
    """Strip accents, lowercase, drop non-alphanumeric — used for fuzzy name match."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", ascii_str.lower())


def load_guild() -> dict:
    if not GUILD_PATH.exists():
        sys.exit("guild.json not found — run fetch_guild.py first")
    return json.loads(GUILD_PATH.read_text(encoding="utf-8"))


def load_requirements() -> dict:
    return json.loads(REQ_PATH.read_text(encoding="utf-8"))


def build_owner_index(members: list) -> tuple[dict, dict, list]:
    """
    Returns:
      owners[norm_name] = list of (player_name, relic_tier, rarity, combat_type)
      name_lookup[norm_name] = display name (canonical from API)
      missing_players: list of player_name without cache file
    """
    owners = defaultdict(list)
    name_lookup = {}
    missing = []
    for m in members:
        ally = m["ally_code"]
        path = PLAYER_DIR / f"{ally}.json"
        if not path.exists():
            missing.append(m["player_name"])
            continue
        player = json.loads(path.read_text(encoding="utf-8"))
        for u in player.get("units", []):
            d = u.get("data", {})
            name = d.get("name", "")
            key = normalize(name)
            if not key:
                continue
            name_lookup.setdefault(key, name)
            owners[key].append((
                m["player_name"],
                d.get("relic_tier") or 0,
                d.get("rarity") or 0,
                d.get("combat_type") or 0,
            ))
    return owners, name_lookup, missing


def eligible_owners(records: list, char_min_relic: int, ship_min_rarity: int) -> tuple[int, int]:
    """Return (eligible_count, combat_type) — combat_type derived from any record."""
    if not records:
        return 0, 0
    ct = records[0][3]
    if ct == 1:  # character — translate game relic to API relic_tier
        api_threshold = char_min_relic + RELIC_OFFSET
        eligible = sum(1 for _, r, _, _ in records if r >= api_threshold)
    else:  # ship
        eligible = sum(1 for _, _, rar, _ in records if rar >= ship_min_rarity)
    return eligible, ct


def analyze(requirements: dict, owners: dict, name_lookup: dict, members_count: int) -> dict:
    results = []
    for op in requirements["operations"]:
        op_rows = []
        for req in op["units"]:
            key = normalize(req["name"])
            recs = owners.get(key, [])
            elig, ct = eligible_owners(
                recs,
                op["char_min_relic"],
                op["ship_min_rarity"],
            )
            op_rows.append({
                "required_name": req["name"],
                "matched_name": name_lookup.get(key),
                "needed": req["count"],
                "eligible": elig,
                "owners_total": len(recs),
                "deficit": max(0, req["count"] - elig),
                "combat_type": ct,
                "matched": key in owners,
            })
        results.append({
            "name": op["name"],
            "pool": op.get("pool", op["name"]),
            "char_min_relic": op["char_min_relic"],
            "ship_min_rarity": op["ship_min_rarity"],
            "rows": op_rows,
        })
    return {"members": members_count, "operations": results}


def fmt_row(r: dict) -> str:
    name = r["required_name"]
    if not r["matched"]:
        flag = "  ❌NOT FOUND"
    elif r["matched_name"] != r["required_name"]:
        flag = f"  (matched: {r['matched_name']})"
    else:
        flag = ""
    ct_label = "char" if r["combat_type"] == 1 else "ship" if r["combat_type"] == 2 else "?"
    deficit_str = f"-{r['deficit']}" if r["deficit"] > 0 else "OK"
    return f"  {name:<32s} {ct_label}  need {r['needed']:>2d}  have {r['eligible']:>2d}/{r['owners_total']:>2d}  {deficit_str}{flag}"


def combined_view(report: dict) -> dict:
    """Aggregate demand per unit within each pool (= phase). Different pools are
    independent battles — a unit can deploy once per pool, so no cross-pool sum."""
    pools = {}
    for op in report["operations"]:
        by_key = pools.setdefault(op.get("pool", op["name"]), {})
        for r in op["rows"]:
            k = r["required_name"]
            entry = by_key.setdefault(k, {
                "name": k,
                "matched_name": r["matched_name"],
                "matched": r["matched"],
                "combat_type": r["combat_type"],
                "needed": 0,
                "owners_total": r["owners_total"],
                "eligible": r["eligible"],
                "ops": [],
            })
            entry["needed"] += r["needed"]
            entry["ops"].append(f"{op['name']}×{r['needed']}")
    out = {}
    for pool, by_key in pools.items():
        rows = list(by_key.values())
        for r in rows:
            r["deficit"] = max(0, r["needed"] - r["eligible"])
        out[pool] = rows
    return out


def print_report(report: dict):
    members = report["members"]
    print(f"\nGuild members analysed: {members}")

    grand_needed = grand_eligible = grand_deficit = 0
    for op in report["operations"]:
        op_needed = sum(r["needed"] for r in op["rows"])
        op_deficit = sum(r["deficit"] for r in op["rows"])
        op_eligible = op_needed - op_deficit
        grand_needed += op_needed
        grand_eligible += op_eligible
        grand_deficit += op_deficit

        print(f"\n=== Operation: {op['name']}  (chars R{op['char_min_relic']}+, ships {op['ship_min_rarity']}*+) ===")
        print(f"Total slots: {op_needed}  |  Filled: {op_eligible}  |  Short: {op_deficit}")
        print()
        rows = sorted(op["rows"], key=lambda r: (-r["deficit"], -r["needed"], r["required_name"]))
        for r in rows:
            print(fmt_row(r))

    print(f"\n{'='*60}")
    print(f"PER-OP TOTAL  needed={grand_needed}  filled={grand_eligible}  short={grand_deficit}")
    print("(per-op view ignores shared-pool conflicts — see combined view below)")

    # Combined view: aggregate demand per unit within each pool (phase)
    for pool, rows in combined_view(report).items():
        combined_short = [r for r in rows if r["deficit"] > 0]
        combined_short.sort(key=lambda r: (-r["deficit"], -r["needed"], r["name"]))
        total_short = sum(r["deficit"] for r in combined_short)
        total_need = sum(r["needed"] for r in rows)
        print(f"\n{'='*60}")
        print(f"COMBINED DEMAND — pool: {pool} (each unit deploys once per pool)")
        print(f"Aggregate slots needed: {total_need}  |  TRUE SHORT: {total_short}  |  units short: {len(combined_short)}\n")
        for r in combined_short:
            ct = "char" if r["combat_type"] == 1 else "ship" if r["combat_type"] == 2 else "?"
            ops = " + ".join(r["ops"])
            print(f"  {r['name']:<32s} {ct}  need {r['needed']:>2d}  have {r['eligible']:>2d}/{r['owners_total']:>2d}  -{r['deficit']}   [{ops}]")


def write_markdown(report: dict, out_path: Path):
    lines = ["# TB Operation Gap Report\n", f"Members analysed: {report['members']}\n"]
    grand_needed = grand_deficit = 0
    for op in report["operations"]:
        op_needed = sum(r["needed"] for r in op["rows"])
        op_deficit = sum(r["deficit"] for r in op["rows"])
        grand_needed += op_needed
        grand_deficit += op_deficit
        lines.append(f"## {op['name']}  (chars R{op['char_min_relic']}+, ships {op['ship_min_rarity']}*+)\n")
        lines.append(f"**Total slots:** {op_needed}  |  **Short:** {op_deficit}\n\n")
        lines.append("| Unit | Type | Need | Have / Owners | Deficit |")
        lines.append("|---|---|---:|---:|---:|")
        rows = sorted(op["rows"], key=lambda r: (-r["deficit"], -r["needed"], r["required_name"]))
        for r in rows:
            ct = "char" if r["combat_type"] == 1 else "ship" if r["combat_type"] == 2 else "?"
            d = f"**{r['deficit']}**" if r["deficit"] > 0 else "OK"
            note = "" if r["matched"] else " ❌NOT FOUND"
            lines.append(f"| {r['required_name']}{note} | {ct} | {r['needed']} | {r['eligible']}/{r['owners_total']} | {d} |")
        lines.append("")
    lines.append(f"\n**PER-OP TOTAL — needed {grand_needed}, short {grand_deficit}**")
    lines.append("\n_(per-op view ignores shared-pool conflicts)_\n")

    # Combined view (per pool)
    for pool, rows in combined_view(report).items():
        combined_short = [r for r in rows if r["deficit"] > 0]
        combined_short.sort(key=lambda r: (-r["deficit"], -r["needed"], r["name"]))
        total_short = sum(r["deficit"] for r in combined_short)
        total_need = sum(r["needed"] for r in rows)
        lines.append(f"## Combined Demand — pool: {pool}\n")
        lines.append(f"Aggregate need: {total_need}  |  **TRUE SHORT: {total_short}**\n")
        if combined_short:
            lines.append("| Unit | Type | Total Need | Have | Owners | Short | Ops |")
            lines.append("|---|---|---:|---:|---:|---:|---|")
            for r in combined_short:
                ct = "char" if r["combat_type"] == 1 else "ship" if r["combat_type"] == 2 else "?"
                ops = " + ".join(r["ops"])
                lines.append(f"| {r['name']} | {ct} | {r['needed']} | {r['eligible']} | {r['owners_total']} | **{r['deficit']}** | {ops} |")
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[markdown report written to {out_path}]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", help="Also write Markdown report to this path")
    args = parser.parse_args()

    guild = load_guild()
    requirements = load_requirements()
    members = guild["data"]["members"]
    owners, name_lookup, missing = build_owner_index(members)
    if missing:
        print(f"⚠ {len(missing)} player(s) missing cache: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")

    report = analyze(requirements, owners, name_lookup, len(members) - len(missing))
    print_report(report)

    if args.report:
        write_markdown(report, Path(args.report))


if __name__ == "__main__":
    main()
