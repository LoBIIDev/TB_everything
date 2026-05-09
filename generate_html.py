"""
Generate a self-contained HTML gap report for the guild to view.

Output: docs/index.html (suitable for GitHub Pages, surge.sh, or any static host)

Usage:
    python generate_html.py
"""
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYER_DIR = ROOT / "cache" / "players"
GUILD_PATH = ROOT / "cache" / "guild.json"
REQ_PATH = ROOT / "requirements.json"
OUT_PATH = ROOT / "docs" / "index.html"

RELIC_OFFSET = 2  # API relic_tier - 2 = in-game relic level


def normalize(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", ascii_str.lower())


def load_data():
    if not GUILD_PATH.exists():
        sys.exit("guild.json missing — run fetch_guild.py first")
    guild = json.loads(GUILD_PATH.read_text(encoding="utf-8"))
    requirements = json.loads(REQ_PATH.read_text(encoding="utf-8"))
    return guild, requirements


def collect(members, target_keys):
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
                "rarity": d.get("rarity") or 0,
                "gear_level": d.get("gear_level") or 0,
                "relic_tier": d.get("relic_tier") or 0,
                "power": d.get("power") or 0,
                "combat_type": d.get("combat_type") or 0,
            })
    return owners, name_lookup


def build_unit_rows(requirements, owners, name_lookup):
    """Return combined per-unit rows + per-op breakdown."""
    by_key = {}
    for op in requirements["operations"]:
        for u in op["units"]:
            key = normalize(u["name"])
            entry = by_key.setdefault(key, {
                "key": key,
                "name": u["name"],
                "needed": 0,
                "ops": [],
                "char_min_relic": op["char_min_relic"],
                "ship_min_rarity": op["ship_min_rarity"],
            })
            entry["needed"] += u["count"]
            entry["ops"].append({"op": op["name"], "count": u["count"]})
    rows = []
    for entry in by_key.values():
        recs = owners.get(entry["key"], [])
        ct = recs[0]["combat_type"] if recs else 0
        # Determine eligible
        if ct == 2:
            api_thr = entry["ship_min_rarity"]
            metric_key = "rarity"
            metric_label = "*"
            display_threshold = entry["ship_min_rarity"]
            display_offset = 0
        else:
            api_thr = entry["char_min_relic"] + RELIC_OFFSET
            metric_key = "relic_tier"
            metric_label = "R"
            display_threshold = entry["char_min_relic"]
            display_offset = RELIC_OFFSET
        eligible = sum(1 for r in recs if r[metric_key] >= api_thr)
        deficit = max(0, entry["needed"] - eligible)

        # Sort owners: above threshold first by metric desc, then below by metric desc
        owners_sorted = sorted(
            recs,
            key=lambda r: (-(1 if r[metric_key] >= api_thr else 0), -r[metric_key], -r["power"]),
        )
        owners_view = [{
            "player": r["player"],
            "metric": r[metric_key] - display_offset if ct != 2 else r[metric_key],
            "ready": r[metric_key] >= api_thr,
            "gear": r["gear_level"],
            "rarity": r["rarity"],
        } for r in owners_sorted]

        rows.append({
            "name": entry["name"],
            "matched_name": name_lookup.get(entry["key"]),
            "matched": entry["key"] in owners and len(owners[entry["key"]]) > 0,
            "combat_type": ct,
            "needed": entry["needed"],
            "eligible": eligible,
            "owners_total": len(recs),
            "deficit": deficit,
            "ops": entry["ops"],
            "metric_label": metric_label,
            "threshold": display_threshold,
            "owners": owners_view,
        })
    rows.sort(key=lambda r: (-r["deficit"], -r["needed"], r["name"]))
    return rows


CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", sans-serif;
       margin: 0; background: #0f172a; color: #e2e8f0; line-height: 1.5; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 24px 16px 80px; }
header { padding: 24px 0 16px; border-bottom: 1px solid #1e293b; margin-bottom: 24px; }
h1 { margin: 0 0 4px; font-size: 24px; }
.meta { color: #94a3b8; font-size: 13px; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 16px 0 24px; }
.stat { background: #1e293b; border-radius: 12px; padding: 14px 16px; }
.stat .label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
.stat .value { font-size: 24px; font-weight: 700; margin-top: 4px; }
.stat.warn .value { color: #f97316; }
.stat.ok .value { color: #22c55e; }
section h2 { font-size: 18px; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #1e293b; }
.unit { background: #1e293b; border-radius: 10px; margin-bottom: 8px; overflow: hidden; }
.unit-row { display: grid; grid-template-columns: 1fr auto auto auto auto; gap: 12px; align-items: center;
            padding: 10px 14px; cursor: pointer; user-select: none; }
.unit-row:hover { background: #243248; }
.unit-name { font-weight: 600; font-size: 14px; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #334155; color: #cbd5e1; }
.badge.char { background: #1e3a5f; color: #93c5fd; }
.badge.ship { background: #3a1e5f; color: #c4b5fd; }
.need { font-size: 13px; color: #cbd5e1; tabular-nums: 1; }
.deficit { font-size: 13px; font-weight: 700; padding: 2px 10px; border-radius: 999px; }
.deficit.short { background: #7f1d1d; color: #fecaca; }
.deficit.ok { background: #14532d; color: #bbf7d0; }
.expand { color: #64748b; font-size: 12px; transition: transform 0.2s; }
.unit.open .expand { transform: rotate(90deg); }
.owners { display: none; padding: 8px 14px 14px; border-top: 1px solid #334155; background: #182234; }
.unit.open .owners { display: block; }
.owners-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 6px; margin-top: 8px; }
.owner { display: flex; justify-content: space-between; align-items: center; padding: 5px 9px;
         background: #0f172a; border-radius: 6px; font-size: 12px; }
.owner.ready { border-left: 3px solid #22c55e; }
.owner.below { border-left: 3px solid #475569; }
.owner .pn { color: #e2e8f0; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.owner .mt { color: #fbbf24; font-weight: 600; tabular-nums: 1; font-size: 11px; }
.owner.ready .mt { color: #4ade80; }
.ops-tag { font-size: 11px; color: #94a3b8; margin-top: 4px; }
.controls { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.controls input { background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
                  padding: 6px 12px; border-radius: 8px; font-size: 13px; min-width: 200px; }
.controls button { background: #1e293b; border: 1px solid #334155; color: #cbd5e1;
                   padding: 6px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.controls button.active { background: #f97316; border-color: #f97316; color: white; }
.controls button:hover:not(.active) { background: #334155; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #1e293b;
         color: #64748b; font-size: 12px; text-align: center; }
"""

JS = """
function toggleUnit(el) { el.parentElement.classList.toggle('open'); }
function applyFilter() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  const showOnlyShort = document.getElementById('only-short').classList.contains('active');
  document.querySelectorAll('.unit').forEach(u => {
    const name = u.dataset.name.toLowerCase();
    const isShort = u.dataset.deficit !== '0';
    const match = !q || name.includes(q);
    const visible = match && (!showOnlyShort || isShort);
    u.style.display = visible ? '' : 'none';
  });
}
function toggleOnlyShort(btn) { btn.classList.toggle('active'); applyFilter(); }
window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('search').addEventListener('input', applyFilter);
});
"""


def render(guild, rows, members_count):
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    total_need = sum(r["needed"] for r in rows)
    total_deficit = sum(r["deficit"] for r in rows)
    total_filled = total_need - total_deficit
    short_units = sum(1 for r in rows if r["deficit"] > 0)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-Hant"><head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{html.escape(guild["data"]["name"])} — TB Operation 缺口</title>',
        f"<style>{CSS}</style>",
        f"<script>{JS}</script>",
        "</head><body>",
        '<div class="wrap">',
        "<header>",
        f'<h1>{html.escape(guild["data"]["name"])} — TB Operation 缺口</h1>',
        f'<div class="meta">最後更新 {html.escape(now)}　|　成員 {members_count} 人</div>',
        "</header>",
        '<div class="summary">',
        f'<div class="stat"><div class="label">需求總槽</div><div class="value">{total_need}</div></div>',
        f'<div class="stat ok"><div class="label">已滿足</div><div class="value">{total_filled}</div></div>',
        f'<div class="stat warn"><div class="label">真實缺口</div><div class="value">{total_deficit}</div></div>',
        f'<div class="stat"><div class="label">缺角數</div><div class="value">{short_units}</div></div>',
        "</div>",
        '<div class="controls">',
        '<input id="search" placeholder="搜尋角色名稱…">',
        '<button id="only-short" class="active" onclick="toggleOnlyShort(this)">只看缺口</button>',
        "</div>",
        "<section><h2>角色缺口（同 phase 共池視角）</h2>",
    ]

    for r in rows:
        ct_class = "char" if r["combat_type"] == 1 else "ship"
        ct_label = "char" if r["combat_type"] == 1 else "ship"
        deficit_class = "short" if r["deficit"] > 0 else "ok"
        deficit_text = f"-{r['deficit']}" if r["deficit"] > 0 else "OK"
        ops_str = " + ".join(f"{html.escape(o['op'])}×{o['count']}" for o in r["ops"])
        owners_html = []
        for o in r["owners"]:
            cls = "ready" if o["ready"] else "below"
            metric = f"{r['metric_label']}{o['metric']}"
            owners_html.append(
                f'<div class="owner {cls}">'
                f'<span class="pn">{html.escape(o["player"])}</span>'
                f'<span class="mt">{metric}</span></div>'
            )
        owners_block = "".join(owners_html) or '<div style="color:#64748b;font-size:12px;padding:6px 0">無人擁有</div>'

        parts.extend([
            f'<div class="unit" data-name="{html.escape(r["name"])}" data-deficit="{r["deficit"]}">',
            '<div class="unit-row" onclick="toggleUnit(this)">',
            f'<div><div class="unit-name">{html.escape(r["name"])}</div>',
            f'<div class="ops-tag">{ops_str}</div></div>',
            f'<span class="badge {ct_class}">{ct_label}</span>',
            f'<span class="need">需 {r["needed"]} · 有 {r["eligible"]}/{r["owners_total"]}</span>',
            f'<span class="deficit {deficit_class}">{deficit_text}</span>',
            '<span class="expand">▶</span>',
            "</div>",
            '<div class="owners">',
            f'<div style="font-size:11px;color:#94a3b8;margin-bottom:4px">擁有者（綠 = 達門檻 {r["metric_label"]}{r["threshold"]}+）</div>',
            f'<div class="owners-grid">{owners_block}</div>',
            "</div></div>",
        ])

    parts.extend([
        "</section>",
        '<footer>data: swgoh.gg API · generated by swgoh_TB</footer>',
        "</div></body></html>",
    ])
    return "\n".join(parts)


def main():
    guild, requirements = load_data()
    members = guild["data"]["members"]
    target_keys = {normalize(u["name"]) for op in requirements["operations"] for u in op["units"]}
    owners, name_lookup = collect(members, target_keys)
    rows = build_unit_rows(requirements, owners, name_lookup)
    html_text = render(guild, rows, members_count=len(members))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html_text, encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[wrote] {OUT_PATH} ({size_kb:.1f} KB)")
    print(f"[stats] {len(rows)} units · "
          f"need={sum(r['needed'] for r in rows)} "
          f"short={sum(r['deficit'] for r in rows)}")


if __name__ == "__main__":
    main()
