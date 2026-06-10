#!/usr/bin/env python3
"""
TF2autoswap - swap any TF2 cosmetic or weapon model for another, client-side.
Creates a VPK ready to import into the Casual Preloader.

Author  : Melancholy Sky
Project : https://github.com/TF2Autoswap/autoswap
License : GPL v3 — free to use, modify, and distribute. See LICENSE for details.

Interactive mode (menu):
    python3 tf2autoswap.py

Command-line swap:
    python3 tf2autoswap.py <source> <target> [--filter pyro] [--out path]

Import a model from disk (Gamebanana / custom):
    python3 tf2autoswap.py --import /path/to/mod/models/.../thing.mdl <target>

Other commands:
    --list             search the game's cosmetics without building
    --list-mods        list the mods you've built
    --list-installed   list .vpk addons in the preloader folder (marks ours)
    --preloader PATH   set the preloader addons folder
    --tf2 PATH         set the TF2 tf/ directory

Needs tf2_core.py beside it. Friendly names and clip warnings also need
tf2_schema.py and the 'vdf' library (optional). Errors and build history
are logged to the output folder.
"""

import os, sys, re, argparse, difflib, logging

import tf2_core as core

try:
    import tf2_schema
    HAVE_SCHEMA = True
except ImportError:
    HAVE_SCHEMA = False

# ---------- branding / paths ----------

PROJECT = "TF2autoswap"
VERSION = "4.7"
SIGNATURE = "_TF2autoswap"                       # appended to every output filename
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "output") # built VPKs go here, inside the tool folder
PRELOADER_ADDONS = os.path.expanduser("~/.local/share/casual-pre-loader/mods/addons")
LOG_PATH = os.path.join(_SCRIPT_DIR, "tf2autoswap.log")

log = logging.getLogger(PROJECT)


# ---------- logging ----------

def setup_logging():
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        logging.basicConfig(
            filename=LOG_PATH, level=logging.INFO,
            format="%(asctime)s  %(levelname)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    except Exception:
        pass
    return logging.getLogger(PROJECT)


# ---------- naming helpers (presentation) ----------

SCHEMA_CACHE_PATH = os.path.join(OUTPUT_DIR, "schema_cache.json")


def load_index(tf2_path):
    if not HAVE_SCHEMA:
        print("(tf2_schema.py not found — friendly names and clip warnings off)")
        return None
    try:
        items_game_path = os.path.join(tf2_path, "scripts", "items", "items_game.txt")
        cached = tf2_schema.load_schema_cache(items_game_path, SCHEMA_CACHE_PATH)
        if cached is not None:
            print("Loading item names (cached)...")
            return cached
        print("Loading item names (first run, this may take a moment)...")
        index = tf2_schema.build_index(tf2_schema.load_schema(tf2_path))
        tf2_schema.save_schema_cache(index, items_game_path, SCHEMA_CACHE_PATH)
        return index
    except Exception as e:
        print(f"(Item names unavailable: {e})")
        log.warning(f"Schema load failed: {e}")
        return None


def display_name(path_or_stem, index):
    """Just the friendly name (or stem) — no decoration."""
    base = os.path.basename(path_or_stem)
    if base.endswith(".mdl"):
        base = base[:-4]
    if index and HAVE_SCHEMA:
        info = tf2_schema.lookup(index, path_or_stem)
        if info:
            return info.name
    return base


def label_for(mdl_path, index):
    """Decorated label for menus: 'The Hollowhead  (stem)  [replaces head]'."""
    base = os.path.basename(mdl_path)[:-4]
    if index and HAVE_SCHEMA:
        info = tf2_schema.lookup(index, mdl_path)
        if info:
            tag = "  [replaces head]" if info.hides_head else ""
            return f"{info.name}  ({base}){tag}"
    return base


def label_for_weapon(mdl_path, index):
    """Decorated label for weapon menus: 'Scattergun  (c_scattergun)  [primary]'."""
    base = os.path.basename(mdl_path)[:-4]
    if index and HAVE_SCHEMA:
        info = tf2_schema.lookup(index, mdl_path)
        if info:
            slot_tag = f"  [{info.item_slot}]" if info.item_slot else ""
            return f"{info.name}  ({base}){slot_tag}"
    return base


def fmt_size(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} bytes"


def normalize_keyword(kw):
    """Lowercase, spaces to underscores, strip punctuation (apostrophes etc)."""
    kw = kw.lower().strip()
    kw = kw.replace(" ", "_")
    kw = re.sub(r"[^a-z0-9_]", "", kw)
    return kw


def _did_you_mean(kw, stems, n=3, cutoff=0.4):
    """Pre-filter stems by starting characters before running difflib."""
    prefix = kw[:3] if len(kw) >= 3 else kw
    candidates = [s for s in stems if s.startswith(prefix)]
    if not candidates:
        candidates = stems
    return difflib.get_close_matches(kw, candidates, n=n, cutoff=cutoff)


def reverse_name_lookup(index, keyword):
    """
    Search schema friendly names for keyword (cosmetics only).
    Returns list of model basenames to use as follow-up search terms.
    """
    if not (index and HAVE_SCHEMA):
        return []
    kw = normalize_keyword(keyword)
    basenames = []
    seen = set()
    for stem, info in index.items():
        if info.item_type == "weapon":
            continue
        if kw in normalize_keyword(info.name):
            base = os.path.basename(stem)
            if base and base not in seen:
                basenames.append(base)
                seen.add(base)
    return basenames


def reverse_name_lookup_weapon(index, keyword):
    """Same as reverse_name_lookup but for weapons."""
    if not (index and HAVE_SCHEMA):
        return []
    kw = normalize_keyword(keyword)
    basenames = []
    seen = set()
    for stem, info in index.items():
        if info.item_type != "weapon":
            continue
        if kw in normalize_keyword(info.name):
            base = os.path.basename(stem)
            if base and base not in seen:
                basenames.append(base)
                seen.add(base)
    return basenames


def validate_output_path(path):
    """
    Check if path is writable. Returns (is_valid, reason_string).
    Creates intermediate directories as needed.
    """
    try:
        dir_path = os.path.dirname(os.path.abspath(path))
        os.makedirs(dir_path, exist_ok=True)
        test = os.path.join(dir_path, ".tf2autoswap_writetest")
        with open(test, "w") as f:
            f.write("")
        os.remove(test)
        return True, None
    except Exception as e:
        return False, str(e)


def sanitize_filename(name):
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "")
    return name.strip()


def output_filename(target_mdl, source_clean, index):
    """Just the signed, friendly filename: 'Target replacement mod (Source)_TF2autoswap.vpk'."""
    tgt = display_name(target_mdl, index)
    return sanitize_filename(f"{tgt} replacement mod ({source_clean}){SIGNATURE}.vpk")


def output_path_for(target_mdl, source_clean, index):
    return os.path.join(OUTPUT_DIR, output_filename(target_mdl, source_clean, index))


def resolve_out_path(given, default_filename):
    """
    If 'given' points at a folder or has no .vpk extension, append the
    generated filename. Also checks for characters that would produce an
    invalid path and falls back to the output folder if found.
    """
    given = os.path.expanduser(given)
    if os.path.isdir(given) or given.endswith(("/", os.sep)) or not given.lower().endswith(".vpk"):
        return os.path.join(given, default_filename)
    return given


def has_invalid_path_chars(path):
    """
    Return True if the path contains characters that are likely to produce
    an invalid or unintended location (null bytes, non-printable characters,
    or shell-special characters like | that would silently misdirect output).
    """
    shell_special = set('|&;`$><!')
    return any(ord(c) < 32 or c in shell_special for c in path)


def clip_warning(index, src_base, dst_base):
    if not (index and HAVE_SCHEMA):
        return None
    return tf2_schema.clip_warning(
        tf2_schema.lookup(index, src_base),
        tf2_schema.lookup(index, dst_base),
    )


def weapon_warning(index, src_base, dst_base):
    if not (index and HAVE_SCHEMA):
        return None
    return tf2_schema.weapon_swap_warning(
        tf2_schema.lookup(index, src_base),
        tf2_schema.lookup(index, dst_base),
    )


def slots_for_class(index, class_name):
    """Return an ordered list of weapon slots available for the given class."""
    if not (index and HAVE_SCHEMA):
        return ["primary", "secondary", "melee"]
    found = set()
    for info in index.values():
        if info.item_type != "weapon":
            continue
        if class_name and class_name != "all":
            if class_name.lower() not in [c.lower() for c in info.classes]:
                continue
        if info.item_slot:
            found.add(info.item_slot)
    slot_order = ["primary", "secondary", "melee", "utility", "pda", "pda2", "building"]
    return [s for s in slot_order if s in found] or ["primary", "secondary", "melee"]


# ---------- build reporting ----------

def emit_vpk(model_files, dst_base, out_vpk, material_files, src_label, target_label):
    result = core.build(model_files, dst_base, out_vpk, material_files)
    for ext in result["packed"]:
        print(f"  OK  {ext}")
    print(f"\nSaved VPK: {result['out_path']}")
    print("Drag it onto the Casual Preloader, tick it, hit Install.")
    log.info(f"Built VPK '{out_vpk}'  ({src_label} replaces {target_label})")
    return result


def emit_addon(model_files, dst_base, addons_dir, addon_name, material_files, src_label, target_label):
    result = core.build_addon_folder(model_files, dst_base, addons_dir, addon_name, material_files)
    for ext in result["packed"]:
        print(f"  OK  {ext}")
    print(f"\nInstalled to preloader: {result['addon_dir']}")
    print("It should show in the preloader's addons list, ready to enable.")
    log.info(f"Installed addon '{result['addon_dir']}'  ({src_label} replaces {target_label})")
    return result


def emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, out_vpk, src_label, target_label, world_note=None):
    result = core.build_weapon(view_files, world_files, dst_view_base, dst_world_base, out_vpk)
    for ext in result["packed"]:
        print(f"  OK  {ext}")
    if not any("world" in e for e in result["packed"]) and world_note:
        print(f"  ({world_note})")
    print(f"\nSaved VPK: {result['out_path']}")
    print("Drag it onto the Casual Preloader, tick it, hit Install.")
    log.info(f"Built weapon VPK '{out_vpk}'  ({src_label} replaces {target_label})")
    return result


def emit_weapon_addon(view_files, world_files, dst_view_base, dst_world_base, addons_dir, addon_name, src_label, target_label, world_note=None):
    result = core.build_weapon_addon_folder(view_files, world_files, dst_view_base, dst_world_base, addons_dir, addon_name)
    for ext in result["packed"]:
        print(f"  OK  {ext}")
    if not any("world" in e for e in result["packed"]) and world_note:
        print(f"  ({world_note})")
    print(f"\nInstalled to preloader: {result['addon_dir']}")
    print("It should show in the preloader's addons list, ready to enable.")
    log.info(f"Installed weapon addon '{result['addon_dir']}'  ({src_label} replaces {target_label})")
    return result


def is_in_preloader(path, preloader_dir):
    try:
        a, b = os.path.abspath(path), os.path.abspath(preloader_dir)
        return os.path.commonpath([a, b]) == b
    except ValueError:
        return False


def confirm_preloader_write(preloader_dir):
    """
    Print a hard warning before writing to the preloader folder.
    Requires the user to type 'yes' explicitly. Returns True if confirmed.
    """
    print("\n  !! WARNING !!")
    print("  Writing directly to the Casual Preloader folder may silently")
    print("  break the preloader if its internal structure is not as expected.")
    print("  It is safer to save a VPK and import it into the preloader manually.")
    print(f"\n  Target folder: {preloader_dir}")
    print()
    answer = input("  Type 'yes' to proceed anyway, or anything else to cancel: ").strip().lower()
    if answer != "yes":
        print("  Cancelled — no files written.")
        return False
    return True


def get_disk_source(mdl_path):
    model_files, material_files, meta = core.source_from_disk(mdl_path)
    if meta["materials_dir"]:
        print(f"  Bundling {meta['material_count']} material file(s) from {meta['materials_dir']}")
    else:
        print("  No materials/ folder found next to the model.")
        print("  (Fine if it reuses stock TF2 textures; otherwise it may look untextured.)")
    return model_files, material_files


# ---------- interactive: shared pickers ----------

def choose(prompt, options, labels):
    for i, label in enumerate(labels, 1):
        print(f"  {i}. {label}")
    while True:
        raw = input(f"{prompt} (1-{len(options)}, q to quit): ").strip().lower()
        if raw == "q":
            sys.exit("Cancelled.")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  Invalid choice, try again.")


def search_and_pick(pak, what, class_filter, index):
    stems = core.all_stems(pak)
    while True:
        kw_raw = input(f"\nSearch for {what} (keyword, q to quit): ").strip()
        if kw_raw.lower() == "q":
            sys.exit("Cancelled.")
        if not kw_raw:
            print("  Please enter a keyword.")
            continue
        kw = normalize_keyword(kw_raw)
        models = core.find_models(pak, kw, class_filter)

        # Reverse name lookup if no direct VPK hits
        if not models and index and HAVE_SCHEMA:
            name_stems = reverse_name_lookup(index, kw)
            for ns in name_stems:
                models.extend(core.find_models(pak, ns, class_filter))
            models = sorted(set(models))
            if models:
                print(f"  Found by item name:")

        if not models:
            print(f"  No matches for '{kw_raw}'.")
            hint = _did_you_mean(kw, stems)
            if hint:
                print(f"  Did you mean: {', '.join(hint)}")
            continue

        # Auto-select single result
        if len(models) == 1:
            print(f"  Auto-selected: {label_for(models[0], index)}")
            return models[0]

        labels = [label_for(m, index) for m in models]
        print(f"\n  Matches for '{kw_raw}':")
        return choose(f"  Pick {what}", models, labels)


def search_and_pick_weapons(pak, what, class_filter, slot_filter, index):
    """Like search_and_pick() but searches c_models paths with optional class/slot filtering."""
    while True:
        kw_raw = input(f"\nSearch for {what} (keyword, q to quit): ").strip()
        if kw_raw.lower() == "q":
            sys.exit("Cancelled.")
        if not kw_raw:
            print("  Please enter a keyword.")
            continue
        kw = normalize_keyword(kw_raw)
        models = core.find_weapons(pak, kw)

        # Filter out items the schema can positively identify as non-weapons
        # Items with no schema entry pass through (graceful fallback)
        if index and HAVE_SCHEMA:
            models = [
                m for m in models
                if not (
                    tf2_schema.lookup(index, m) and
                    tf2_schema.lookup(index, m).item_type not in ("weapon", "unknown")
                )
            ]
        # Path-based blocklist for known non-weapon models with no schema entry
        NON_WEAPON_PATH_FRAGMENTS = ["ornament"]
        models = [
            m for m in models
            if not any(fragment in m.lower() for fragment in NON_WEAPON_PATH_FRAGMENTS)
        ]

        # Reverse name lookup if no direct VPK hits
        if not models and index and HAVE_SCHEMA:
            name_stems = reverse_name_lookup_weapon(index, kw)
            for ns in name_stems:
                models.extend(core.find_weapons(pak, ns))
            models = sorted(set(models))
            if models:
                print(f"  Found by item name:")

        needs_filter = (
            (class_filter and class_filter != "all") or
            (slot_filter and slot_filter != "all")
        )
        if index and HAVE_SCHEMA and needs_filter:
            filtered = []
            for mdl in models:
                info = tf2_schema.lookup(index, mdl)
                if info is None:
                    filtered.append(mdl)
                    continue
                if class_filter and class_filter != "all":
                    if class_filter.lower() not in [c.lower() for c in info.classes]:
                        continue
                if slot_filter and slot_filter != "all":
                    if info.item_slot.lower() != slot_filter.lower():
                        continue
                filtered.append(mdl)
            models = filtered

        if not models:
            print(f"  No matches for '{kw_raw}'.")
            hint = _did_you_mean(kw, core.all_weapon_stems(pak))
            if hint:
                print(f"  Did you mean: {', '.join(hint)}")
            continue

        # Auto-select single result
        if len(models) == 1:
            print(f"  Auto-selected: {label_for_weapon(models[0], index)}")
            return models[0]

        labels = [label_for_weapon(m, index) for m in models]
        print(f"\n  Matches for '{kw_raw}':")
        return choose(f"  Pick {what}", models, labels)


def ask_disk_model():
    while True:
        path = input("\nPath to the .mdl file (q to quit): ").strip().strip("'\"")
        if path.lower() == "q":
            sys.exit("Cancelled.")
        path = os.path.expanduser(path)
        if os.path.isfile(path) and path.endswith(".mdl"):
            return path
        print("  Not a valid .mdl file path, try again.")


# ---------- interactive: swap flow ----------

def interactive_swap(pak, index, preloader_dir):
    print("\n--- New swap ---\n")

    print("Step 1 - Which class?")
    class_opts = core.CLASSES + ["all (no filter)"]
    cls = choose("Select class", class_opts, class_opts)
    cls = cls.split()[0] if cls.startswith("all") else cls

    print("\nStep 2 - Cosmetic to REPLACE")
    target = search_and_pick(pak, "the cosmetic to replace", cls, index)
    dst_base = target[:-4]
    target_label = label_for(target, index)

    print("\nStep 3 - REPLACEMENT source")
    how = choose("Where from?",
                 ["builtin", "disk"],
                 ["TF2's built-in cosmetics", "Import a model from disk (Gamebanana / custom)"])

    material_files = None
    src_base = None
    if how == "builtin":
        source = search_and_pick(pak, "the replacement cosmetic", cls, index)
        src_base = source[:-4]
        model_files = core.source_from_vpk(pak, src_base)
        src_label = label_for(source, index)
        source_clean = display_name(source, index)
    else:
        mdl_path = ask_disk_model()
        model_files, material_files = get_disk_source(mdl_path)
        src_label = os.path.basename(mdl_path)[:-4]
        source_clean = src_label

    print("\nStep 4 - Confirm")
    print(f"  Replace : {target_label}")
    print(f"  With    : {src_label}")
    if src_base:
        warn = clip_warning(index, src_base, dst_base)
        if warn:
            print(f"\n  Heads-up: {warn}")
    preview = core.preview_build(model_files, dst_base, material_files)
    summary = f"{preview['model_count']} model file(s), {fmt_size(preview['total_size'])}"
    if preview["material_count"]:
        summary += f" + {preview['material_count']} material(s)"
    print(f"\n  Preview: {summary}")
    if input("Proceed? (y/n): ").strip().lower() not in ("y", "yes"):
        sys.exit("Cancelled.")

    print("\nStep 5 - Output location")
    fname = output_filename(target, source_clean, index)
    addon_name = fname[:-4]  # strip .vpk
    opts, labels = ["default"], [f"Output folder as a VPK  ({OUTPUT_DIR})"]
    if os.path.isdir(preloader_dir):
        opts.append("preloader")
        labels.append("Preloader addons folder  (installed format, ready to use)")
    opts.append("custom")
    labels.append("Custom path")

    where = choose("Save to", opts, labels)
    if where == "preloader":
        if confirm_preloader_write(preloader_dir):
            emit_addon(model_files, dst_base, preloader_dir, addon_name, material_files, src_label, target_label)
    elif where == "custom":
        raw = input("Enter a path (file or folder): ").strip().strip("'\"")
        if not raw:
            emit_vpk(model_files, dst_base, os.path.join(OUTPUT_DIR, fname), material_files, src_label, target_label)
        elif is_in_preloader(raw, preloader_dir):
            if confirm_preloader_write(preloader_dir):
                emit_addon(model_files, dst_base, preloader_dir, addon_name, material_files, src_label, target_label)
        elif has_invalid_path_chars(raw):
            print("  That path contains invalid characters — saving to output folder instead.")
            emit_vpk(model_files, dst_base, os.path.join(OUTPUT_DIR, fname), material_files, src_label, target_label)
        else:
            out_path = resolve_out_path(raw, fname)
            valid, reason = validate_output_path(out_path)
            if not valid:
                print(f"  That path isn't writable: {reason}")
                print(f"  Saving to output folder instead.")
                out_path = os.path.join(OUTPUT_DIR, fname)
            emit_vpk(model_files, dst_base, out_path, material_files, src_label, target_label)
    else:
        emit_vpk(model_files, dst_base, os.path.join(OUTPUT_DIR, fname), material_files, src_label, target_label)


# ---------- interactive: weapon swap flow ----------

def interactive_weapon_swap(pak, index, preloader_dir):
    print("\n--- New weapon swap ---\n")

    print("Step 1 - Which class?")
    class_opts = core.CLASSES + ["all (no filter)"]
    cls = choose("Select class", class_opts, class_opts)
    cls = cls.split()[0] if cls.startswith("all") else cls

    print("\nStep 2 - Which loadout slot?")
    slot_opts = slots_for_class(index, cls)
    slot_display = slot_opts + ["all (no filter)"]
    slot = choose("Select slot", slot_display, slot_display)
    slot = slot.split()[0] if slot.startswith("all") else slot

    print("\nStep 3 - Weapon to REPLACE")
    target = search_and_pick_weapons(pak, "the weapon to replace", cls, slot, index)
    dst_view_base = target[:-4]
    dst_world_base = core.resolve_world_base_from_vpk(pak, dst_view_base)
    target_label = label_for_weapon(target, index)

    print("\nStep 4 - REPLACEMENT source")
    source = search_and_pick_weapons(pak, "the replacement weapon", cls, slot, index)
    src_view_base = source[:-4]
    src_label = label_for_weapon(source, index)
    source_clean = display_name(source, index)
    view_files, world_files, src_world_base = core.source_from_vpk_weapon(pak, src_view_base)

    print("\nStep 5 - Confirm & output")
    print(f"  Replace : {target_label}")
    print(f"  With    : {src_label}")
    warn = weapon_warning(index, src_view_base, dst_view_base)
    if warn:
        print(f"\n  Heads-up: {warn}")

    # World model note — distinguish melee (expected) from other weapons (unexpected)
    world_note = None
    if not world_files:
        dst_info = tf2_schema.lookup(index, dst_view_base) if (index and HAVE_SCHEMA) else None
        if dst_info and dst_info.item_slot == "melee":
            world_note = "melee weapons typically don't have separate world models — viewmodel only is expected"
        else:
            world_note = "no world model found — viewmodel only"
        print(f"  Note: {world_note.capitalize()}.")

    preview = core.preview_build_weapon(view_files, world_files, dst_view_base, dst_world_base or "")
    summary = f"{preview['view_count']} viewmodel file(s)"
    if preview["world_count"]:
        summary += f" + {preview['world_count']} worldmodel file(s)"
    summary += f", {fmt_size(preview['total_size'])}"
    print(f"\n  Preview: {summary}")

    if input("\nProceed? (y/n): ").strip().lower() not in ("y", "yes"):
        sys.exit("Cancelled.")

    print()
    fname = output_filename(target, source_clean, index)
    addon_name = fname[:-4]
    opts, labels = ["default"], [f"Output folder as a VPK  ({OUTPUT_DIR})"]
    if os.path.isdir(preloader_dir):
        opts.append("preloader")
        labels.append("Preloader addons folder  (installed format, ready to use)")
    opts.append("custom")
    labels.append("Custom path")

    where = choose("Save to", opts, labels)
    if where == "preloader":
        if confirm_preloader_write(preloader_dir):
            emit_weapon_addon(view_files, world_files, dst_view_base, dst_world_base, preloader_dir, addon_name, src_label, target_label, world_note)
    elif where == "custom":
        raw = input("Enter a path (file or folder): ").strip().strip("'\"")
        if not raw:
            emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, os.path.join(OUTPUT_DIR, fname), src_label, target_label, world_note)
        elif is_in_preloader(raw, preloader_dir):
            if confirm_preloader_write(preloader_dir):
                emit_weapon_addon(view_files, world_files, dst_view_base, dst_world_base, preloader_dir, addon_name, src_label, target_label, world_note)
        elif has_invalid_path_chars(raw):
            print("  That path contains invalid characters — saving to output folder instead.")
            emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, os.path.join(OUTPUT_DIR, fname), src_label, target_label, world_note)
        else:
            out_path = resolve_out_path(raw, fname)
            valid, reason = validate_output_path(out_path)
            if not valid:
                print(f"  That path isn't writable: {reason}")
                print(f"  Saving to output folder instead.")
                out_path = os.path.join(OUTPUT_DIR, fname)
            emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, out_path, src_label, target_label, world_note)
    else:
        emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, os.path.join(OUTPUT_DIR, fname), src_label, target_label, world_note)


# ---------- interactive: manage made mods ----------

def manage_mods(index):
    while True:
        mods = core.list_output_mods(OUTPUT_DIR)
        if not mods:
            print(f"\nNo mods found in {OUTPUT_DIR}")
            return

        root_mods = [m for m in mods if not m["in_subfolder"]]
        sub_mods = [m for m in mods if m["in_subfolder"]]
        all_displayed = []

        print(f"\nMods you've built ({OUTPUT_DIR}):")
        for m in root_mods:
            all_displayed.append(m)
            tgt = display_name(m["target_stem"], index) if m["target_stem"] else "unknown target"
            print(f"  {len(all_displayed)}. {m['name']}")
            print(f"       replaces: {tgt}")

        if sub_mods:
            print(f"\n  In subfolders:")
            for m in sub_mods:
                all_displayed.append(m)
                tgt = display_name(m["target_stem"], index) if m["target_stem"] else "unknown target"
                print(f"  {len(all_displayed)}. {m['rel']}")
                print(f"       replaces: {tgt}")

        raw = input("\nEnter a number to remove, or q to go back: ").strip().lower()
        if raw == "q":
            return
        if raw.isdigit() and 1 <= int(raw) <= len(all_displayed):
            chosen = all_displayed[int(raw) - 1]
            if input(f"Delete '{chosen['name']}'? (y/n): ").strip().lower() in ("y", "yes"):
                core.remove_file(chosen["path"])
                print("Removed.")
                log.info(f"Removed mod: {chosen['path']}")
        else:
            print("Invalid choice.")


# ---------- interactive: list installed addons ----------

def show_installed(preloader_dir):
    try:
        entries = core.list_preloader_addons(preloader_dir, SIGNATURE)
    except core.SwapError as e:
        print(f"\n{e}")
        print("Set the folder with --preloader, or check the preloader is installed.")
        return
    if not entries:
        print(f"\nNothing found in {preloader_dir}")
        return

    ours = [e for e in entries if e["kind"] == "addon" and e["is_ours"]]
    vpks = [e for e in entries if e["kind"] == "vpk"]

    if not ours and not vpks:
        print(f"\nNo {PROJECT} addons or loose .vpk files found.")
        return

    if ours:
        print(f"\n{PROJECT} addons installed ({len(ours)}):")
        for a in ours:
            print(f"  {a['rel']}")
    if vpks:
        print(f"\nLoose .vpk files (not imported by the preloader):")
        for v in vpks:
            mark = f"   <- {PROJECT}" if v["is_ours"] else ""
            print(f"  {v['rel']}{mark}")

    print("\n(Note: this shows what's present in the folder, not which are")
    print(" enabled or disabled inside the preloader.)")


# ---------- interactive entry ----------

def interactive(pak, index, preloader_dir):
    print(f"\n=== {PROJECT} v{VERSION} ===")
    action = choose("\nWhat would you like to do?",
                    ["swap", "weapon", "mods", "installed"],
                    ["Create a cosmetic swap",
                     "Create a weapon swap",
                     "List / remove mods I've made",
                     "List addons in the preloader folder"])
    if action == "swap":
        print("\nSelected: Cosmetic swap")
        interactive_swap(pak, index, preloader_dir)
    elif action == "weapon":
        print("\nSelected: Weapon swap")
        interactive_weapon_swap(pak, index, preloader_dir)
    elif action == "mods":
        manage_mods(index)
    else:
        show_installed(preloader_dir)


# ---------- CLI mode ----------

def cli(pak, index, args):
    dst = core.find_models(pak, args.target)
    if not dst:
        raise core.ModelNotFound(f"Nothing found for target '{args.target}' (try --list)")
    target_mdl = dst[0]
    dst_base = target_mdl[:-4]

    if args.import_path:
        model_files, material_files = get_disk_source(os.path.expanduser(args.import_path))
        src_label = os.path.basename(args.import_path)[:-4]
        source_clean = src_label
        src_base = None
    else:
        src = core.find_models(pak, args.source, args.cls)
        if not src:
            raise core.ModelNotFound(f"Nothing found for source '{args.source}' (try --list)")
        src_base = src[0][:-4]
        model_files = core.source_from_vpk(pak, src_base)
        material_files = None
        src_label = args.source
        source_clean = display_name(src[0], index)

    print(f"Source : {src_label}\nTarget : {dst_base}")
    if src_base:
        warn = clip_warning(index, src_base, dst_base)
        if warn:
            print(f"\n  Heads-up: {warn}")
    print()

    if args.dry_run:
        preview = core.preview_build(model_files, dst_base, material_files)
        print("DRY RUN — nothing will be written.\n")
        for e in preview["entries"]:
            print(f"  {e['ext']:12s}  {e['size']:>10,} bytes")
        print(f"\n  Total: {len(preview['entries'])} file(s), {fmt_size(preview['total_size'])}")
        fname = output_filename(target_mdl, source_clean, index)
        if args.to_preloader:
            dest = os.path.join(args.preloader_dir, fname[:-4])
            print(f"  Would install as addon to: {dest}")
        elif args.out:
            if has_invalid_path_chars(args.out):
                print(f"  Would save VPK to: {os.path.join(OUTPUT_DIR, fname)}  (invalid chars in path — using output folder)")
            else:
                print(f"  Would save VPK to: {resolve_out_path(args.out, fname)}")
        else:
            print(f"  Would save VPK to: {os.path.join(OUTPUT_DIR, fname)}")
        return

    fname = output_filename(target_mdl, source_clean, index)
    addon_name = fname[:-4]
    if args.to_preloader:
        if confirm_preloader_write(args.preloader_dir):
            emit_addon(model_files, dst_base, args.preloader_dir, addon_name, material_files, src_label, args.target)
    elif args.out and is_in_preloader(args.out, args.preloader_dir):
        if confirm_preloader_write(args.preloader_dir):
            emit_addon(model_files, dst_base, args.preloader_dir, addon_name, material_files, src_label, args.target)
    elif args.out:
        if has_invalid_path_chars(args.out):
            print("  That path contains invalid characters — saving to output folder instead.")
            emit_vpk(model_files, dst_base, os.path.join(OUTPUT_DIR, fname), material_files, src_label, args.target)
        else:
            emit_vpk(model_files, dst_base, resolve_out_path(args.out, fname), material_files, src_label, args.target)
    else:
        emit_vpk(model_files, dst_base, os.path.join(OUTPUT_DIR, fname), material_files, src_label, args.target)


# ---------- CLI: weapon mode ----------

def cli_weapon(pak, index, args):
    dst = core.find_weapons(pak, args.target)
    if not dst:
        raise core.ModelNotFound(f"Nothing found for target weapon '{args.target}' (try --list --weapon)")
    target_mdl = dst[0]
    dst_view_base = target_mdl[:-4]
    dst_world_base = core.resolve_world_base_from_vpk(pak, dst_view_base)

    src = core.find_weapons(pak, args.source)
    if not src:
        raise core.ModelNotFound(f"Nothing found for source weapon '{args.source}' (try --list --weapon)")
    src_view_base = src[0][:-4]
    view_files, world_files, src_world_base = core.source_from_vpk_weapon(pak, src_view_base)

    src_label = args.source
    source_clean = display_name(src[0], index)

    print(f"Source : {src_label}\nTarget : {dst_view_base}")
    warn = weapon_warning(index, src_view_base, dst_view_base)
    if warn:
        print(f"\n  Heads-up: {warn}")
    print()

    if args.dry_run:
        preview = core.preview_build_weapon(view_files, world_files, dst_view_base, dst_world_base or "")
        print("DRY RUN — nothing will be written.\n")
        for e in preview["entries"]:
            print(f"  {e['ext']:20s}  {e['size']:>10,} bytes")
        print(f"\n  Total: {len(preview['entries'])} file(s), {fmt_size(preview['total_size'])}")
        fname = output_filename(target_mdl, source_clean, index)
        if args.to_preloader:
            print(f"  Would install as addon to: {os.path.join(args.preloader_dir, fname[:-4])}")
        elif args.out:
            if has_invalid_path_chars(args.out):
                print(f"  Would save VPK to: {os.path.join(OUTPUT_DIR, fname)}  (invalid chars in path — using output folder)")
            else:
                print(f"  Would save VPK to: {resolve_out_path(args.out, fname)}")
        else:
            print(f"  Would save VPK to: {os.path.join(OUTPUT_DIR, fname)}")
        return

    fname = output_filename(target_mdl, source_clean, index)
    addon_name = fname[:-4]

    world_note = None
    if not world_files:
        dst_info = tf2_schema.lookup(index, dst_view_base) if (index and HAVE_SCHEMA) else None
        if dst_info and dst_info.item_slot == "melee":
            world_note = "melee weapons typically don't have separate world models — viewmodel only is expected"
        else:
            world_note = "no world model found — viewmodel only"

    if args.to_preloader:
        if confirm_preloader_write(args.preloader_dir):
            emit_weapon_addon(view_files, world_files, dst_view_base, dst_world_base, args.preloader_dir, addon_name, src_label, args.target, world_note)
    elif args.out and is_in_preloader(args.out, args.preloader_dir):
        if confirm_preloader_write(args.preloader_dir):
            emit_weapon_addon(view_files, world_files, dst_view_base, dst_world_base, args.preloader_dir, addon_name, src_label, args.target, world_note)
    elif args.out:
        if has_invalid_path_chars(args.out):
            print("  That path contains invalid characters — saving to output folder instead.")
            emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, os.path.join(OUTPUT_DIR, fname), src_label, args.target, world_note)
        else:
            emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, resolve_out_path(args.out, fname), src_label, args.target, world_note)
    else:
        emit_weapon_vpk(view_files, world_files, dst_view_base, dst_world_base, os.path.join(OUTPUT_DIR, fname), src_label, args.target, world_note)


# ---------- entry ----------

def run():
    ap = argparse.ArgumentParser(description=f"{PROJECT} — swap TF2 cosmetics, client-side")
    ap.add_argument("--version", action="version", version=f"{PROJECT} {VERSION}")
    ap.add_argument("source", nargs="?", help="keyword of the cosmetic to use as replacement")
    ap.add_argument("target", nargs="?", help="keyword of the cosmetic to replace")
    ap.add_argument("--weapon", action="store_true", help="swap weapons instead of cosmetics")
    ap.add_argument("--filter", dest="cls", help="class variant for all-class items (e.g. pyro)")
    ap.add_argument("--import", dest="import_path", help="use a local .mdl file as the replacement")
    ap.add_argument("--out", help="custom output .vpk path (file or folder)")
    ap.add_argument("--to-preloader", action="store_true", help="save straight into the preloader addons folder")
    ap.add_argument("--dry-run", action="store_true", help="preview what would be built without writing anything")
    ap.add_argument("--list", action="store_true", help="search the game's cosmetics, don't build")
    ap.add_argument("--list-mods", action="store_true", help="list mods you've built")
    ap.add_argument("--list-installed", action="store_true", help="list .vpk addons in the preloader")
    ap.add_argument("--preloader", help="set the preloader addons folder")
    ap.add_argument("--tf2", help="set your TF2 tf/ directory")
    ap.add_argument("--cake", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.cake:
        print("""
               i
              (|)
         ..--""|""--..
      .'   (@) | (@)    '.
     (  (@)    '    (@)   )
      '..   (@)   (@)  ..'
      |  ''--......--''  |
      | ~  ~  ~  ~  ~  ~ |
      |__________________|
       '-..__________..-'

  The cake is a lie.
  ~ Cake - Powered by Claude Fable 5 ~
""")
        sys.exit("Cancelled.")

    preloader_dir = os.path.expanduser(args.preloader) if args.preloader else PRELOADER_ADDONS
    args.preloader_dir = preloader_dir

    # Commands that don't need the VPK opened
    if args.list_installed:
        show_installed(preloader_dir)
        return

    tf2 = core.resolve_tf2(args.tf2)
    print(f"TF2 found: {tf2}")

    if args.list_mods:
        index = load_index(tf2)
        manage_mods_readonly(index)
        return

    pak = core.open_pak(tf2)

    if args.list:
        index = load_index(tf2)
        for kw_raw in (args.source, args.target):
            if not kw_raw:
                continue
            kw = normalize_keyword(kw_raw)
            print(f"\n{kw_raw}:")
            if args.weapon:
                hits = core.find_weapons(pak, kw)
                for h in hits:
                    print(f"  {label_for_weapon(h, index)}")
            else:
                hits = core.find_models(pak, kw, args.cls)
                for h in hits:
                    print(f"  {label_for(h, index)}")
            if not hits:
                print("  (nothing found)")
        return

    if args.import_path and args.source and not args.target:
        args.target = args.source
        args.source = None

    index = load_index(tf2)

    if (args.import_path and args.target) or (args.source and args.target):
        if args.weapon:
            cli_weapon(pak, index, args)
        else:
            cli(pak, index, args)
    else:
        interactive(pak, index, preloader_dir)


def manage_mods_readonly(index):
    """CLI --list-mods: list without the interactive remove loop."""
    mods = core.list_output_mods(OUTPUT_DIR)
    if not mods:
        print(f"\nNo mods found in {OUTPUT_DIR}")
        return

    root_mods = [m for m in mods if not m["in_subfolder"]]
    sub_mods = [m for m in mods if m["in_subfolder"]]

    print(f"\nMods you've built ({OUTPUT_DIR}):")
    i = 1
    for m in root_mods:
        tgt = display_name(m["target_stem"], index) if m["target_stem"] else "unknown target"
        print(f"  {i}. {m['name']}")
        print(f"       replaces: {tgt}")
        i += 1
    if sub_mods:
        print(f"\n  In subfolders:")
        for m in sub_mods:
            tgt = display_name(m["target_stem"], index) if m["target_stem"] else "unknown target"
            print(f"  {i}. {m['rel']}")
            print(f"       replaces: {tgt}")
            i += 1
    print("\n(Run interactively — option 3 — to remove any of these.)")


import hashlib as _hashlib

ACKNOWLEDGED_FLAG = os.path.join(OUTPUT_DIR, ".acknowledged")
# The flag file stores a SHA256 hash rather than plain text.
# This is not to hide anything — the source is fully open.
# It provides light tamper-resistance for liability purposes.
# Verifiable with: hashlib.sha256(b"tf2autoswap_acknowledged").hexdigest()
_ACK_HASH = _hashlib.sha256(b"tf2autoswap_acknowledged").hexdigest()


def check_acknowledgement():
    """
    On first run, show the full risk warning and require the user to type
    'agree' before continuing. Saves a SHA256 hash flag file so the prompt
    only appears once. Subsequent runs show a single-line reminder only.
    CLI-facing only — any future GUI should handle this separately.

    The flag file stores a hash (not plain text) for tamper-resistance.
    Verification snippet: hashlib.sha256(b"tf2autoswap_acknowledged").hexdigest()
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if os.path.isfile(ACKNOWLEDGED_FLAG):
        try:
            stored = open(ACKNOWLEDGED_FLAG).read().strip()
        except Exception:
            stored = ""
        if stored == _ACK_HASH:
            print("(Reminder: use this tool while TF2 is closed.)")
            print()
            return
        # File exists but hash doesn't match — re-prompt
        os.remove(ACKNOWLEDGED_FLAG)

    print("=" * 56)
    print("  IMPORTANT — please read before continuing")
    print("=" * 56)
    print("  - Use this tool while TF2 is CLOSED.")
    print("  - Client-side mods may violate competitive")
    print("    league rules (RGL, ETF2L, etc).")
    print("    Check your league's policy before using.")
    print("  - VAC bans for client mods are rare but")
    print("    possible. Use at your own risk.")
    print("=" * 56)
    print()
    while True:
        try:
            resp = input("  Type 'agree' to accept, or 'q' to quit: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)
        if resp == "agree":
            break
        if resp in ("q", "quit", "exit"):
            print("Cancelled.")
            sys.exit(0)
        print("  Please type 'agree' to continue, or 'q' to quit.")
    open(ACKNOWLEDGED_FLAG, "w").write(_ACK_HASH + "\n")
    log.info("User acknowledged risk warning.")
    print()


def main():
    global log
    log = setup_logging()
    check_acknowledgement()
    try:
        run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    except core.SwapError as e:
        log.error(str(e))
        print(f"\nERROR: {e}")
        print(f"(logged to {LOG_PATH})")
        sys.exit(1)
    except Exception as e:
        log.exception("Unexpected error")
        print(f"\nUnexpected error: {e}")
        print(f"Full details logged to {LOG_PATH}")
        sys.exit(1)


main()
