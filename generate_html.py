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
    """Returns owners[key]=[{...}] + per-player roster keyed by normalized name."""
    owners = {k: [] for k in target_keys}
    name_lookup = {}
    by_player = {}
    for m in members:
        path = PLAYER_DIR / f"{m['ally_code']}.json"
        if not path.exists():
            continue
        player = json.loads(path.read_text(encoding="utf-8"))
        roster = {}
        for u in player.get("units", []):
            d = u.get("data", {})
            key = normalize(d.get("name", ""))
            if not key:
                continue
            omicrons_learned = {
                a["id"] for a in (d.get("ability_data") or [])
                if a.get("has_omicron_learned")
            }
            rec = {
                "player": m["player_name"],
                "rarity": d.get("rarity") or 0,
                "gear_level": d.get("gear_level") or 0,
                "relic_tier": d.get("relic_tier") or 0,
                "power": d.get("power") or 0,
                "combat_type": d.get("combat_type") or 0,
                "omicrons_learned": omicrons_learned,
            }
            roster[key] = rec
            if key in target_keys:
                name_lookup.setdefault(key, d.get("name"))
                owners[key].append(rec)
        by_player[m["ally_code"]] = {"name": m["player_name"], "roster": roster}
    return owners, name_lookup, by_player


def _check_candidate(rec, candidate, api_threshold) -> tuple[bool, str]:
    """Check if a roster record satisfies a single any_of candidate. Returns (ok, reason_if_not)."""
    if rec is None:
        return False, "未擁有"
    if rec["relic_tier"] < api_threshold:
        game_r = max(0, rec["relic_tier"] - RELIC_OFFSET)
        return False, f"R{game_r} < 門檻"
    omicron_id = candidate.get("require_omicron")
    if omicron_id and omicron_id not in rec.get("omicrons_learned", set()):
        return False, "缺 Omicron"
    return True, ""


def build_special_missions(special_missions, by_player):
    """For each SM, find players who have at least one passing candidate per slot."""
    results = []
    for sm in special_missions:
        slots = []
        for req in sm["required_chars"]:
            cands = []
            for c in req["any_of"]:
                # Accept either string or object form
                if isinstance(c, str):
                    cands.append({"name": c, "key": normalize(c)})
                else:
                    cands.append({**c, "key": normalize(c["name"])})
            slots.append({
                "label": req["label"],
                "min_relic": req["min_relic"],
                "api_threshold": req["min_relic"] + RELIC_OFFSET,
                "candidates": cands,
            })

        qualified, partial = [], []

        for ally, p in by_player.items():
            roster = p["roster"]
            slot_status = []
            for s in slots:
                best_pass = None
                best_fail = None  # for display: closest-to-pass candidate
                for c in s["candidates"]:
                    rec = roster.get(c["key"])
                    ok, reason = _check_candidate(rec, c, s["api_threshold"])
                    if ok:
                        if best_pass is None or rec["relic_tier"] > best_pass["rec"]["relic_tier"]:
                            best_pass = {"candidate": c, "rec": rec, "reason": ""}
                    else:
                        if rec is not None and (best_fail is None or rec["relic_tier"] > best_fail["rec"]["relic_tier"]):
                            best_fail = {"candidate": c, "rec": rec, "reason": reason}
                slot_status.append({
                    "slot": s,
                    "best_pass": best_pass,
                    "best_fail": best_fail,
                    "passes": best_pass is not None,
                })
            passes = sum(1 for s in slot_status if s["passes"])
            row = {"player": p["name"], "slot_status": slot_status, "passes": passes}
            if passes == len(slots):
                qualified.append(row)
            else:
                partial.append(row)

        # Sort partial: most slots passed first, then highest avg relic
        def pkey(r):
            ss = r["slot_status"]
            avg = 0
            for s in ss:
                rec = (s["best_pass"] or s["best_fail"] or {}).get("rec")
                avg += rec["relic_tier"] if rec else 0
            avg /= max(1, len(ss))
            return (-r["passes"], -avg)
        partial.sort(key=pkey)
        qualified.sort(key=lambda r: r["player"])

        total_players = len(by_player)
        target_raw = sm.get("guild_target", sm.get("min_successful_attempts", 0))
        target = total_players if target_raw == "all" else int(target_raw)

        results.append({
            "name": sm["name"],
            "purpose": sm["purpose"],
            "needed": target,
            "min_required": sm.get("min_successful_attempts", 0),
            "target_label": "全員達標" if target_raw == "all" else f"{target} 人",
            "slots": slots,
            "qualified": qualified,
            "partial": partial,
            "total_players": total_players,
        })
    return results


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
.tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid #1e293b; }
.tab { padding: 10px 18px; background: transparent; border: none; color: #94a3b8;
       font-size: 14px; font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent;
       transition: all 0.2s; }
.tab:hover { color: #e2e8f0; }
.tab.active { color: #f97316; border-bottom-color: #f97316; }
.page { display: none; }
.page.active { display: block; }
.sm-card { background: #1e293b; border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
.sm-title { font-size: 16px; font-weight: 700; margin: 0 0 4px; }
.sm-purpose { color: #94a3b8; font-size: 13px; margin-bottom: 14px; }
.sm-progress { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.bar { flex: 1; height: 14px; background: #0f172a; border-radius: 999px; overflow: hidden; position: relative; }
.bar-fill { height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); transition: width 0.5s; }
.bar-fill.short { background: linear-gradient(90deg, #f97316, #fbbf24); }
.bar-text { font-size: 13px; font-weight: 700; color: #e2e8f0; tabular-nums: 1; min-width: 100px; }
.sm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
.sm-slot { background: #0f172a; border-radius: 8px; padding: 12px 14px; }
.sm-slot h4 { margin: 0 0 6px; font-size: 13px; color: #cbd5e1; }
.sm-slot .count { color: #4ade80; font-weight: 700; }
.sm-slot .count.short { color: #fbbf24; }
.player-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
.player-chip { font-size: 11px; padding: 2px 8px; background: #1e293b; border-radius: 999px;
               color: #cbd5e1; }
.player-chip.ready { background: #14532d; color: #bbf7d0; }
.player-chip.partial { background: #78350f; color: #fed7aa; }
.qualified-block { margin-top: 18px; padding-top: 14px; border-top: 1px solid #334155; }
.qualified-block h4 { margin: 0 0 8px; font-size: 13px; color: #e2e8f0; }
.partial-row { font-size: 12px; padding: 6px 10px; background: #0f172a; border-radius: 6px;
               margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center; }
.partial-row .pn { color: #cbd5e1; }
.partial-row .ss { color: #94a3b8; font-size: 11px; }
"""

JS = """
function toggleUnit(el) { el.parentElement.classList.toggle('open'); }
function applyFilter() {
  const sb = document.getElementById('search'); if (!sb) return;
  const q = sb.value.trim().toLowerCase();
  const onlyShortBtn = document.getElementById('only-short');
  const showOnlyShort = onlyShortBtn && onlyShortBtn.classList.contains('active');
  document.querySelectorAll('#page-ops .unit').forEach(u => {
    const name = u.dataset.name.toLowerCase();
    const isShort = u.dataset.deficit !== '0';
    const match = !q || name.includes(q);
    const visible = match && (!showOnlyShort || isShort);
    u.style.display = visible ? '' : 'none';
  });
}
function toggleOnlyShort(btn) { btn.classList.toggle('active'); applyFilter(); }
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + name));
  history.replaceState(null, '', '#' + name);
}
window.addEventListener('DOMContentLoaded', () => {
  const sb = document.getElementById('search');
  if (sb) sb.addEventListener('input', applyFilter);
  const initial = (location.hash || '#ops').slice(1);
  showTab(document.querySelector('.tab[data-tab="'+initial+'"]') ? initial : 'ops');
});
"""


def render_ops_page(rows):
    total_need = sum(r["needed"] for r in rows)
    total_deficit = sum(r["deficit"] for r in rows)
    total_filled = total_need - total_deficit
    short_units = sum(1 for r in rows if r["deficit"] > 0)

    parts = ['<div id="page-ops" class="page">']
    parts.extend([
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
    ])
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
    parts.append("</section></div>")
    return "".join(parts)


def render_sm_page(sms):
    parts = ['<div id="page-sm" class="page">']
    if not sms:
        parts.append('<p style="color:#94a3b8">尚無 Special Mission 設定。</p>')
    for sm in sms:
        qcount = len(sm["qualified"])
        needed = sm["needed"]
        progress_pct = min(100, qcount * 100 / max(1, needed))
        bar_class = "" if qcount >= needed else "short"
        deficit = max(0, needed - qcount)
        progress_label = f"{qcount} / {needed}" + (f"  (差 {deficit} 人)" if deficit else "  ✓")
        # Sub-line: 遊戲最低門檻
        min_req = sm.get("min_required", 0)
        sub_line = ""
        if min_req:
            min_status = "✓ 已過" if qcount >= min_req else f"差 {min_req - qcount} 人"
            sub_line = (f'<div style="font-size:11px;color:#94a3b8;margin-top:4px">'
                        f'目標：{html.escape(sm.get("target_label",""))}　·　'
                        f'遊戲最低門檻：{min_req} 人 ({min_status})</div>')

        parts.extend([
            '<div class="sm-card">',
            f'<h3 class="sm-title">{html.escape(sm["name"])}</h3>',
            f'<div class="sm-purpose">{html.escape(sm["purpose"])}</div>',
            '<div class="sm-progress">',
            f'<div class="bar"><div class="bar-fill {bar_class}" style="width:{progress_pct:.1f}%"></div></div>',
            f'<div class="bar-text">{progress_label}</div>',
            "</div>",
            sub_line,
            '<div class="sm-grid">',
        ])

        # Per-slot snapshot: how many at threshold for each slot
        for s in sm["slots"]:
            ready_players = []
            below_players = []
            for row in sm["qualified"] + sm["partial"]:
                st = next((x for x in row["slot_status"] if x["slot"] is s), None)
                if not st:
                    continue
                if st["best_pass"]:
                    ready_players.append(row["player"])
                elif st["best_fail"]:
                    rec = st["best_fail"]["rec"]
                    game_r = max(0, rec["relic_tier"] - RELIC_OFFSET)
                    below_players.append(f"{row['player']} (R{game_r}, {st['best_fail']['reason']})")
            count_class = "" if len(ready_players) >= sm["total_players"] else "short"
            cand_names = ", ".join(html.escape(c["name"]) for c in s["candidates"])
            req_extra = []
            for c in s["candidates"]:
                if c.get("require_omicron"):
                    req_extra.append(f"{html.escape(c['name'])}: +{html.escape(c.get('omicron_label', c['require_omicron']))}")
            extra_html = (
                "<div style='font-size:11px;color:#fbbf24;margin-top:4px'>"
                + " · ".join(req_extra) + "</div>"
            ) if req_extra else ""

            parts.extend([
                '<div class="sm-slot">',
                f'<h4>{html.escape(s["label"])} <span style="color:#64748b">(R{s["min_relic"]}+)</span></h4>',
                f'<div style="font-size:11px;color:#94a3b8">候選：{cand_names}</div>',
                extra_html,
                f'<div style="margin-top:8px"><span class="count {count_class}">{len(ready_players)}</span>'
                f' <span style="color:#64748b">/ {sm["total_players"]} 達門檻</span></div>',
            ])
            if below_players:
                parts.append(f'<div style="font-size:11px;color:#94a3b8;margin-top:6px">'
                             f'未達 {len(below_players)} 人</div>')
            parts.append("</div>")
        parts.append("</div>")  # sm-grid

        # Qualified / Partial player lists
        parts.append('<div class="qualified-block">')
        parts.append(f'<h4>✓ 可清關玩家 ({qcount})</h4>')
        if sm["qualified"]:
            chips = "".join(f'<span class="player-chip ready">{html.escape(r["player"])}</span>'
                            for r in sm["qualified"])
            parts.append(f'<div class="player-list">{chips}</div>')
        else:
            parts.append('<div style="color:#64748b;font-size:12px">尚無</div>')

        # Partial: show all rows missing 1 slot, sorted by "easiest to upgrade"
        almost = [r for r in sm["partial"] if r["passes"] == len(sm["slots"]) - 1]
        if almost:
            parts.append(f'<h4 style="margin-top:14px">⚠ 差 1 隻達標 ({len(almost)})</h4>')
            for r in almost[:30]:
                missing_parts = []
                for st in r["slot_status"]:
                    if st["passes"]:
                        continue
                    s = st["slot"]
                    if st["best_fail"]:
                        rec = st["best_fail"]["rec"]
                        game_r = max(0, rec["relic_tier"] - RELIC_OFFSET)
                        cn = st["best_fail"]["candidate"]["name"]
                        missing_parts.append(f"{html.escape(s['label'])}: {html.escape(cn)} R{game_r} → {st['best_fail']['reason']}")
                    else:
                        missing_parts.append(f"{html.escape(s['label'])}: 未擁有")
                parts.append(
                    '<div class="partial-row">'
                    f'<span class="pn">{html.escape(r["player"])}</span>'
                    f'<span class="ss">{" / ".join(missing_parts)}</span>'
                    "</div>"
                )

        parts.append("</div></div>")  # qualified-block + sm-card

    parts.append("</div>")
    return "".join(parts)


def render(guild, rows, sms, members_count):
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    parts = [
        "<!DOCTYPE html>",
        '<html lang="zh-Hant"><head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{html.escape(guild["data"]["name"])} — TB 戰備</title>',
        f"<style>{CSS}</style>",
        f"<script>{JS}</script>",
        "</head><body>",
        '<div class="wrap">',
        "<header>",
        f'<h1>{html.escape(guild["data"]["name"])} — TB 戰備</h1>',
        f'<div class="meta">最後更新 {html.escape(now)}　|　成員 {members_count} 人</div>',
        "</header>",
        '<div class="tabs">',
        '<button class="tab" data-tab="ops" onclick="showTab(\'ops\')">Operation 缺口</button>',
        '<button class="tab" data-tab="sm" onclick="showTab(\'sm\')">Special Mission</button>',
        "</div>",
        render_ops_page(rows),
        render_sm_page(sms),
        '<footer>data: swgoh.gg API · generated by swgoh_TB</footer>',
        "</div></body></html>",
    ]
    return "\n".join(parts)


def main():
    guild, requirements = load_data()
    members = guild["data"]["members"]

    # Targets: Operation units + Special Mission required chars
    target_keys = {normalize(u["name"]) for op in requirements["operations"] for u in op["units"]}
    for sm in requirements.get("special_missions", []):
        for req in sm["required_chars"]:
            for c in req["any_of"]:
                name = c if isinstance(c, str) else c["name"]
                target_keys.add(normalize(name))

    owners, name_lookup, by_player = collect(members, target_keys)
    rows = build_unit_rows(requirements, owners, name_lookup)
    sms = build_special_missions(requirements.get("special_missions", []), by_player)
    html_text = render(guild, rows, sms, members_count=len(members))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html_text, encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"[wrote] {OUT_PATH} ({size_kb:.1f} KB)")
    print(f"[stats] {len(rows)} op-units · need={sum(r['needed'] for r in rows)} "
          f"short={sum(r['deficit'] for r in rows)} · "
          f"{len(sms)} special mission(s)")
    for sm in sms:
        print(f"  - {sm['name']}: {len(sm['qualified'])}/{sm['needed']} qualified players")


if __name__ == "__main__":
    main()
