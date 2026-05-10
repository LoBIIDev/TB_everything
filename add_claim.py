"""
Add a guild member's claim(s) to claims.yaml.

Player can be: ally_code (numeric, e.g. 749294592)
            OR nickname / display name (case-insensitive contains-match,
               must be unambiguous)

Unit names can be: English (Echo, Eeth Koth)
                OR unit_alias.json shortname (易思考斯)
                OR unit_zh.json 繁中 全名
                OR a comma-separated string

Usage:
    python add_claim.py <player> <unit1> [unit2 ...]
    python add_claim.py <player> "unit1, unit2, unit3"
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

from unit_resolver import build_resolver, resolve as _resolve_name

ROOT = Path(__file__).resolve().parent
GUILD = ROOT / "cache" / "guild.json"
CLAIMS = ROOT / "claims.yaml"


def find_player(query):
    if not GUILD.exists():
        sys.exit("guild.json missing — run fetch_guild.py first")
    guild = json.loads(GUILD.read_text(encoding="utf-8"))
    members = guild["data"]["members"]
    q = str(query).strip()
    # ally_code (numeric, 9 digits)
    if q.isdigit():
        ally = int(q)
        for m in members:
            if m["ally_code"] == ally:
                return m["player_name"]
        sys.exit(f"ally_code {ally} not in guild")
    # exact name (case-insensitive)
    qlow = q.lower()
    for m in members:
        if m["player_name"].strip().lower() == qlow:
            return m["player_name"]
    # contains match (must be unambiguous)
    matches = [m["player_name"] for m in members if qlow in m["player_name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        sys.exit(f"Ambiguous player query '{q}': matches {', '.join(matches[:8])}")
    sys.exit(f"Player not found: {q}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    player_query = sys.argv[1]
    rest = sys.argv[2:]
    if len(rest) == 1 and ("," in rest[0] or "、" in rest[0]):
        unit_args = re.split(r"[,、]", rest[0])
    else:
        unit_args = rest

    player = find_player(player_query)
    resolver = build_resolver()

    canon_units = []
    unknown = []
    for u in unit_args:
        u = u.strip()
        if not u:
            continue
        canon = _resolve_name(u, resolver)
        if canon:
            canon_units.append(canon)
        else:
            unknown.append(u)
            canon_units.append(u)  # still record, but won't auto-prune

    # Load existing claims; canonicalize them so future dedup works regardless of alias form
    raw = yaml.safe_load(CLAIMS.read_text(encoding="utf-8")) or {} if CLAIMS.exists() else {}
    claims = (raw.get("claims") or {}) if isinstance(raw, dict) else {}

    def _canonicalize(items):
        out = []
        seen = set()
        for u in items or []:
            c = _resolve_name(u, resolver) or u
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
        return out

    # Canonicalize ALL existing entries (not just current player) for consistency
    for k in list(claims.keys()):
        claims[k] = _canonicalize(claims[k])

    existing = claims.get(player) or []
    added = []
    for u in canon_units:
        if u not in existing:
            existing.append(u)
            added.append(u)
    claims[player] = existing

    # Preserve top-of-file comments
    original = CLAIMS.read_text(encoding="utf-8") if CLAIMS.exists() else ""
    header_lines = []
    for line in original.splitlines():
        if line.startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    body = yaml.dump({"claims": claims}, allow_unicode=True, sort_keys=False, default_flow_style=False)
    CLAIMS.write_text(
        ("\n".join(header_lines) + "\n" if header_lines else "") + body,
        encoding="utf-8",
    )

    print(f"✓ {player}: 新增 {len(added)} 隻 (重複略過 {len(canon_units) - len(added)})")
    if added:
        print(f"  新增：{', '.join(added)}")
    if unknown:
        print(f"⚠ 名稱無法對應（仍會記錄但不會自動移除）：{', '.join(unknown)}")
    print(f"  該玩家目前認領清單：{', '.join(existing)}")


if __name__ == "__main__":
    main()
