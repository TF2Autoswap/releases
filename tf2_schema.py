#!/usr/bin/env python3
"""
tf2_schema.py - Parse TF2's items_game.txt into a usable item index.

Author  : Melancholy Sky
Project : https://github.com/TF2Autoswap/autoswap
License : GPL v3 — free to use, modify, and distribute. See LICENSE for details.

Provides:
    load_schema(tf2_path)          -> parsed schema dict
    build_index(schema)            -> { model_stem (lowercase, no ext): ItemInfo }
    lookup(index, model_path)      -> ItemInfo or None

ItemInfo fields:
    name          friendly display name (e.g. "A Head Full of Hot Air")
    equip_region  e.g. "hat" or "pyro_head_replacement"
    hides_head    True if equipping this hides the player's head
    classes       list of classes that can use it
"""

import os
import json
from dataclasses import dataclass, field

WEAPON_SLOTS = {"primary", "secondary", "melee", "utility", "pda", "pda2", "building"}
COSMETIC_SLOTS = {"head", "misc", "action", "taunt"}


@dataclass
class ItemInfo:
    name: str
    equip_region: str = ""
    hides_head: bool = False
    classes: list = field(default_factory=list)
    item_type: str = "unknown"    # "cosmetic", "weapon", "unknown"
    item_slot: str = ""           # "primary", "secondary", "melee", etc.
    animation_risk: bool = False  # True for melee weapons (distinct animation rig)


def _need_vdf():
    try:
        import vdf
        return vdf
    except ImportError:
        import sys, subprocess
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "vdf", "--no-warn-script-location"],
            check=True
        )
        import vdf
        return vdf


def load_schema(tf2_path):
    vdf = _need_vdf()
    igt = os.path.join(tf2_path, "scripts", "items", "items_game.txt")
    if not os.path.isfile(igt):
        raise FileNotFoundError(f"items_game.txt not found at {igt}")
    with open(igt, encoding="utf-8", errors="replace") as f:
        return vdf.loads(f.read())


def _deep_merge(base, overlay):
    """Merge overlay onto base (overlay wins). Returns a new dict."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _resolve_prefabs(item, prefabs, _seen=None):
    """
    Merge an item's inherited prefab fields. The 'prefab' field is a
    space-separated list of prefab names, each of which may have its own
    prefab chain. The item's own fields take precedence over inherited ones.
    """
    if _seen is None:
        _seen = set()

    prefab_names = item.get("prefab", "")
    if not prefab_names:
        return dict(item)

    merged = {}
    for pname in prefab_names.split():
        if pname in _seen or pname not in prefabs:
            continue
        _seen.add(pname)
        resolved_prefab = _resolve_prefabs(prefabs[pname], prefabs, _seen)
        merged = _deep_merge(merged, resolved_prefab)

    # Item's own fields override inherited ones
    return _deep_merge(merged, item)


def _model_stems(resolved):
    """Return list of (lowercase, extensionless) model paths for an item."""
    stems = []
    mp = resolved.get("model_player")
    if mp:
        stems.append(mp)
    per = resolved.get("model_player_per_class")
    if isinstance(per, dict):
        basename = per.get("basename")
        if basename and "%s" in basename:
            classes = list(resolved.get("used_by_classes", {}).keys())
            for c in classes:
                stems.append(basename.replace("%s", c))
        else:
            # explicit per-class entries (older format)
            for k, v in per.items():
                if k != "basename" and isinstance(v, str):
                    stems.append(v)
    # normalise: forward slashes, lowercase, strip .mdl
    out = []
    for s in stems:
        s = s.replace("\\", "/").lower()
        if s.endswith(".mdl"):
            s = s[:-4]
        out.append(s)
    return out


def _item_type(resolved):
    slot = resolved.get("item_slot", "").lower()
    if slot in WEAPON_SLOTS:
        return "weapon"
    if slot in COSMETIC_SLOTS:
        return "cosmetic"
    if resolved.get("model_player") or resolved.get("model_player_per_class"):
        return "cosmetic"
    return "unknown"


def _hides_head(resolved):
    region = resolved.get("equip_region", "")
    regions = resolved.get("equip_regions", {})  # some items use plural block
    region_names = [region] + (list(regions.keys()) if isinstance(regions, dict) else [])
    if any("head_replacement" in r for r in region_names if r):
        return True
    bg = resolved.get("visuals", {}).get("player_bodygroups", {})
    if isinstance(bg, dict) and "head" in bg:
        return True
    return False


def build_index(schema):
    root = schema["items_game"]
    prefabs = root.get("prefabs", {})
    items = root["items"]

    index = {}
    for defidx, item in items.items():
        if not isinstance(item, dict) or "name" not in item:
            continue
        resolved = _resolve_prefabs(item, prefabs)

        info = ItemInfo(
            name=item.get("name", "?"),
            equip_region=resolved.get("equip_region", ""),
            hides_head=_hides_head(resolved),
            classes=list(resolved.get("used_by_classes", {}).keys()),
            item_slot=resolved.get("item_slot", "").lower(),
            item_type=_item_type(resolved),
            animation_risk=resolved.get("item_slot", "").lower() == "melee",
        )
        for stem in _model_stems(resolved):
            index[stem] = info
    return index


def lookup(index, model_path):
    """model_path may include .mdl and any slashes/case."""
    s = model_path.replace("\\", "/").lower()
    if s.endswith(".mdl"):
        s = s[:-4]
    return index.get(s)


def clip_warning(source_info, target_info):
    """
    Return a warning string if swapping source onto target may cause visual
    clipping, or None if the swap looks fine.

    Checks in order of severity:
    1. Head clip — source replaces the head but target does not hide it.
    2. Equip region mismatch — source and target cover different areas of the
       player model, so the source model may clip with other equipped items.
    """
    if not (source_info and target_info):
        return None

    # Head clip (specific, high confidence)
    if source_info.hides_head and not target_info.hides_head:
        return (f"'{source_info.name}' replaces the head, but "
                f"'{target_info.name}' doesn't hide the default head — "
                f"it will clip through. An over-the-head model would fit better.")

    # General equip region mismatch
    src_region = source_info.equip_region
    tgt_region = target_info.equip_region
    if src_region and tgt_region and src_region != tgt_region:
        return (f"'{source_info.name}' uses the '{src_region}' equip region "
                f"but '{target_info.name}' uses '{tgt_region}' — "
                f"these cover different areas and may clip with other equipped items.")

    return None


def weapon_swap_warning(source_info, target_info):
    """
    Return a warning string if swapping source onto target may cause issues.
    Main case: slot mismatch (e.g. primary into melee slot) which can
    cause animation or behaviour problems in-game.
    Returns None if the swap looks fine.
    """
    if source_info and target_info:
        src_slot = source_info.item_slot or "unknown"
        tgt_slot = target_info.item_slot or "unknown"
        if src_slot != tgt_slot:
            return (f"'{source_info.name}' is a {src_slot} weapon "
                    f"but '{target_info.name}' is {tgt_slot} — "
                    f"slot mismatch may cause animation or behaviour issues.")
    return None


# ---------- schema cache ----------

def _index_to_dict(index):
    """Serialise {stem: ItemInfo} to a JSON-safe dict."""
    return {
        stem: {
            "name": info.name,
            "equip_region": info.equip_region,
            "hides_head": info.hides_head,
            "classes": info.classes,
            "item_slot": getattr(info, "item_slot", ""),
            "item_type": getattr(info, "item_type", ""),
        }
        for stem, info in index.items()
    }


def _dict_to_index(data):
    """Deserialise a JSON dict back to {stem: ItemInfo}."""
    index = {}
    for stem, d in data.items():
        info = ItemInfo(
            name=d.get("name", "?"),
            equip_region=d.get("equip_region", ""),
            hides_head=d.get("hides_head", False),
            classes=d.get("classes", []),
        )
        if hasattr(info, "item_slot"):
            info.item_slot = d.get("item_slot", "")
        if hasattr(info, "item_type"):
            info.item_type = d.get("item_type", "")
        index[stem] = info
    return index


def save_schema_cache(index, items_game_path, cache_path):
    """
    Save the parsed index to a JSON cache file alongside the
    items_game.txt mtime. Safe to call even if the cache folder
    doesn't exist yet.
    """
    try:
        mtime = os.path.getmtime(items_game_path)
        payload = {"mtime": mtime, "index": _index_to_dict(index)}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass  # cache write failure is non-fatal


def load_schema_cache(items_game_path, cache_path):
    """
    Return a cached index if the cache exists and items_game.txt
    hasn't changed since it was written. Returns None otherwise.
    """
    if not os.path.isfile(cache_path):
        return None
    try:
        mtime = os.path.getmtime(items_game_path)
        with open(cache_path, encoding="utf-8") as f:
            payload = json.load(f)
        if payload.get("mtime") != mtime:
            return None
        return _dict_to_index(payload["index"])
    except Exception:
        return None


# Quick self-test when run directly against a schema file path
if __name__ == "__main__":
    import sys, vdf
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/real_sample.txt"
    with open(path, encoding="utf-8", errors="replace") as f:
        schema = vdf.loads(f.read())
    idx = build_index(schema)
    print(f"Indexed {len(idx)} model paths\n")
    for stem, info in idx.items():
        print(f"  {info.name}")
        print(f"    stem: {stem}")
        print(f"    region: {info.equip_region}  hides_head: {info.hides_head}  classes: {info.classes}")
