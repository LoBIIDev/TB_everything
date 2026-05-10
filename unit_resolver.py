"""Shared unit-name resolver: maps English / alias / 繁中 / common acronym -> canonical English."""
import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "requirements.json"
ALIAS = ROOT / "unit_alias.json"
ZH = ROOT / "unit_zh.json"


# Common SWGoH community initialisms — built-in alongside unit_alias.json
COMMON_ACRONYMS = {
    "Jedi Knight Luke Skywalker": ["JKL"],
    "Jedi Master Luke Skywalker": ["JML"],
    "Commander Luke Skywalker": ["CLS"],
    "Jedi Knight Revan": ["JKR"],
    "Jedi Master Kenobi": ["JMK"],
    "Grand Master Yoda": ["GMY"],
    "General Skywalker": ["GAS"],
    "Supreme Leader Kylo Ren": ["SLKR"],
    "Sith Eternal Emperor": ["SEE"],
    "Lord Vader": ["LV"],
    "Grand Inquisitor": ["GI"],
    "Commander Ahsoka Tano": ["CAT"],
    "Ahsoka Tano (Fulcrum)": ["Fulcrum", "ATF"],
    "Boba Fett, Scion of Jango": ["BFSoJ", "Scion"],
    "Jedi Knight Cal Kestis": ["JKCK"],
    "Cere Junda": ["Cere"],
    "Padmé Amidala": ["Padme"],
    "Emperor Palpatine": ["EP"],
    "Darth Sidious": ["Sidious"],
    "Darth Malgus": ["Malgus"],
    "Darth Malak": ["Malak"],
    "Darth Vader": ["DV"],
    "Han's Millennium Falcon": ["HMF"],
}


def _load_table(path: Path) -> dict:
    if not path.exists():
        return {}
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
            if not k.startswith("_") and v}


def build_resolver(requirements: Optional[dict] = None) -> dict:
    """Return mapping {input.lower().strip(): canonical_english_name}."""
    if requirements is None:
        requirements = json.loads(REQ.read_text(encoding="utf-8"))
    alias_map = _load_table(ALIAS)
    zh_map = _load_table(ZH)

    resolver: dict[str, str] = {}

    def add(canon: str, *names: str):
        for n in (canon, *names):
            if not n:
                continue
            key = n.strip().lower()
            resolver.setdefault(key, canon)

    for op in requirements["operations"]:
        for u in op["units"]:
            add(u["name"])
    for sm in requirements.get("special_missions", []):
        for r in sm["required_chars"]:
            for c in r["any_of"]:
                add(c if isinstance(c, str) else c["name"])
    for k, v in alias_map.items():
        add(k, v)
    for k, v in zh_map.items():
        add(k, v)
    for canon, acros in COMMON_ACRONYMS.items():
        add(canon, *acros)
    return resolver


def resolve(name: str, resolver: dict) -> Optional[str]:
    return resolver.get(str(name).strip().lower())
