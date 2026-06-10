#!/usr/bin/env python3
"""
tf2_core.py - Core logic for the TF2 cosmetic and weapon swap tool.

Author  : Melancholy Sky
Project : https://github.com/TF2Autoswap/autoswap
License : GPL v3 — free to use, modify, and distribute. See LICENSE for details.

Interface-free: every function takes inputs and returns data, or raises a
SwapError on failure. No print() or input() calls live here, so any frontend
(CLI, interactive prompts, a future TUI/GUI) can sit on top of it.
"""

import os, re, tempfile, shutil, subprocess, sys, json


# ---------- exceptions ----------

class SwapError(Exception):
    """Base class for all expected, user-facing errors."""

class TF2NotFound(SwapError):
    pass

class ModelNotFound(SwapError):
    pass

class BuildError(SwapError):
    pass


# ---------- constants ----------

TF2_PATHS = [
    "~/.steam/steam/steamapps/common/Team Fortress 2/tf",
    "~/.local/share/Steam/steamapps/common/Team Fortress 2/tf",
    "C:/Program Files (x86)/Steam/steamapps/common/Team Fortress 2/tf",
    "C:/Program Files/Steam/steamapps/common/Team Fortress 2/tf",
    "~/Library/Application Support/Steam/steamapps/common/Team Fortress 2/tf",
]

CLASSES = ["scout", "soldier", "pyro", "demoman", "heavy",
           "engineer", "medic", "sniper", "spy"]

# Per-class path name variants (model files use shortened names like _demo, _engi)
_CLASS_PATH_TERMS = {
    "scout":    ["scout"],
    "soldier":  ["soldier", "solly"],
    "pyro":     ["pyro"],
    "demoman":  ["demoman", "demo"],
    "heavy":    ["heavy"],
    "engineer": ["engineer", "engi"],
    "medic":    ["medic"],
    "sniper":   ["sniper"],
    "spy":      ["spy"],
}
_ALL_CLASS_PATH_TERMS = sorted(set(
    term for terms in _CLASS_PATH_TERMS.values() for term in terms
))

# Weapon model suffixes that indicate skins, reskins, or non-weapon files
_WEAPON_VARIANT_SUFFIXES = (
    "_festivizer", "_xmas", "_helloween",
    "_animations", "_arms", "_screen", "_bonemerge",
)

EXTS = [".mdl", ".vvd", ".dx80.vtx", ".dx90.vtx", ".sw.vtx"]


# ---------- setup ----------

def get_vpk():
    try:
        import vpk
        return vpk
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "vpk", "--no-warn-script-location"],
            check=True
        )
        import vpk
        return vpk


def resolve_tf2(override=None):
    """Return the TF2 tf/ path, or raise TF2NotFound."""
    paths = [override] if override else [os.path.expanduser(p) for p in TF2_PATHS]
    for path in paths:
        if path and os.path.isfile(os.path.join(path, "tf2_misc_dir.vpk")):
            return path
    raise TF2NotFound("TF2 not found. Set the path manually with the tf/ directory.")


def open_pak(tf2_path):
    vpk = get_vpk()
    return vpk.open(os.path.join(tf2_path, "tf2_misc_dir.vpk"))


# ---------- model search ----------

def find_models(pak, keyword, class_filter=None):
    """Return sorted, deduplicated .mdl paths matching keyword (and class)."""
    kw = keyword.lower().replace(" ", "_")
    hits = [p for p in pak if p.endswith(".mdl") and kw in p.lower()]
    if class_filter and class_filter != "all":
        cf = class_filter.lower()
        cf_terms = _CLASS_PATH_TERMS.get(cf, [cf])
        filtered = []
        for h in hits:
            hl = h.lower()
            # Direct class folder match
            if any(f"/{t}/" in hl for t in cf_terms):
                filtered.append(h)
            # All-class item: include if it matches our class term, or has
            # no class term at all (generic all-class with no per-class variants)
            elif "/all_class/" in hl:
                has_our_class = any(f"_{t}" in hl for t in cf_terms)
                has_other_class = any(
                    f"_{t}" in hl for t in _ALL_CLASS_PATH_TERMS if t not in cf_terms
                )
                if has_our_class or not has_other_class:
                    filtered.append(h)
        hits = filtered
    return sorted(set(hits))


def all_stems(pak):
    return sorted(set(os.path.basename(p)[:-4] for p in pak if p.endswith(".mdl")))


def all_weapon_stems(pak):
    """List every c_model stem — used for weapon 'did you mean' suggestions."""
    return sorted(set(
        os.path.basename(p)[:-4]
        for p in pak
        if "/c_models/" in p.lower() and p.endswith(".mdl")
    ))


def patch_mdl(data, new_name):
    if data[:4] != b'IDST':
        return data
    return data[:12] + new_name.encode()[:63].ljust(64, b'\x00') + data[76:]


# ---------- weapon model helpers ----------

def find_weapons(pak, keyword):
    """
    Return sorted c_model .mdl paths matching keyword.
    Variant suffixes (_festivizer, _xmas, _animations etc) are filtered unless
    the keyword itself is a variant term, so searching 'scattergun' returns
    clean results while searching 'festivizer' still works.
    """
    kw = keyword.lower().replace(" ", "_")
    hits = [
        p for p in pak
        if "/c_models/" in p.lower() and p.endswith(".mdl") and kw in p.lower()
    ]
    # Filter variants unless the keyword is itself a variant term
    variant_search = any(v.strip("_") in kw for v in _WEAPON_VARIANT_SUFFIXES)
    if not variant_search:
        hits = [
            h for h in hits
            if not any(
                os.path.basename(h[:-4]).lower().endswith(s)
                for s in _WEAPON_VARIANT_SUFFIXES
            )
        ]
    # Deduplicate by basename — different VPK paths with the same filename
    # (e.g. workshop vs base) would otherwise show as separate results
    seen_bases = set()
    deduped = []
    for h in sorted(set(hits)):
        base = os.path.basename(h[:-4]).lower()
        if base not in seen_bases:
            seen_bases.add(base)
            deduped.append(h)
    return deduped


def _world_base_candidates(view_base):
    """
    Return possible world model base paths for a viewmodel base, most likely first.
    TF2 uses two structures:
      Subfolder: c_models/c_<name>/c_<name> -> c_models/c_<name>/w_<name>
      Flat:      c_models/c_<name>/c_<name> -> w_models/w_<name>
    Both look identical from the view path alone, so we try both.
    """
    parts = view_base.split("/")
    vname = parts[-1]
    if not vname.lower().startswith("c_"):
        return []
    w_name = "w_" + vname[2:]
    candidates = []
    # Subfolder candidate: world model shares the c_models subfolder
    if len(parts) >= 2:
        candidates.append("/".join(parts[:-1] + [w_name]))
    # Flat candidate: world model in w_models/, dropping the c_<name> subfolder entirely
    # e.g. models/weapons/c_models/c_minigun/c_minigun -> models/weapons/w_models/w_minigun
    c_idx = next((i for i, p in enumerate(parts) if p == "c_models"), None)
    if c_idx is not None:
        flat = "/".join(parts[:c_idx] + ["w_models", w_name])
        if flat not in candidates:
            candidates.append(flat)
    return candidates


def derive_world_base(view_base):
    """Return the primary candidate world model base path. Use
    resolve_world_base_from_vpk() when the pak is available for accuracy."""
    candidates = _world_base_candidates(view_base)
    return candidates[0] if candidates else None


def resolve_world_base_from_vpk(pak, view_base):
    """
    Find the actual world model base path by checking the VPK.
    Tries both possible path structures and returns the one that exists.
    Falls back to the primary candidate if neither is found.
    Use this for destination paths when building weapon swaps.
    """
    for candidate in _world_base_candidates(view_base):
        if source_from_vpk(pak, candidate):
            return candidate
    candidates = _world_base_candidates(view_base)
    return candidates[0] if candidates else None


def source_from_vpk_weapon(pak, view_base):
    """
    Read viewmodel + worldmodel files from the VPK.
    Tries both possible world model path structures and uses whichever has files.
    Returns (view_files, world_files, world_base).
    world_files will be empty ({}) if no world model is found.
    """
    view_files = source_from_vpk(pak, view_base)
    for candidate in _world_base_candidates(view_base):
        world_files = source_from_vpk(pak, candidate)
        if world_files:
            return view_files, world_files, candidate
    return view_files, {}, None


# ---------- source readers ----------

def source_from_vpk(pak, src_base):
    """Return {ext: bytes} for a model already inside TF2's VPK."""
    files = {}
    for ext in EXTS:
        try:
            files[ext] = pak[src_base + ext].read()
        except KeyError:
            pass
    return files


def find_mod_materials(mdl_path):
    parts = os.path.normpath(os.path.abspath(mdl_path)).split(os.sep)
    if "models" in parts:
        idx = parts.index("models")
        root = os.sep.join(parts[:idx]) or os.sep
        mats = os.path.join(root, "materials")
        if os.path.isdir(mats):
            return mats
    return None


def source_from_disk(mdl_path):
    """
    Read a local model and any sibling materials folder.
    Returns (model_files, material_files, meta) where meta describes what
    was found, for the interface to report.
    """
    if not os.path.isfile(mdl_path) or not mdl_path.endswith(".mdl"):
        raise BuildError(f"Not a .mdl file: {mdl_path}")

    base = mdl_path[:-4]
    model_files = {}
    for ext in EXTS:
        p = base + ext
        if os.path.isfile(p):
            model_files[ext] = open(p, "rb").read()

    material_files = {}
    mats = find_mod_materials(mdl_path)
    if mats:
        root = os.path.dirname(mats)
        for dirpath, _, filenames in os.walk(mats):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                material_files[rel] = open(full, "rb").read()

    meta = {"materials_dir": mats, "material_count": len(material_files)}
    return model_files, material_files, meta


# ---------- build ----------

def build(model_files, dst_base, out_path, material_files=None):
    """
    Write the VPK. Returns a result dict:
        {"packed": [exts...], "material_count": n, "out_path": path}
    Raises BuildError on failure.
    """
    if ".mdl" not in model_files:
        raise BuildError("No .mdl found in the source model.")

    tmpdir = tempfile.mkdtemp()
    packed = []
    try:
        for ext, data in model_files.items():
            if ext == ".mdl":
                data = patch_mdl(data, dst_base)
            out = os.path.join(tmpdir, *((dst_base + ext).split("/")))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)
            packed.append(ext)

        for vpk_path, data in (material_files or {}).items():
            out = os.path.join(tmpdir, *vpk_path.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)

        vpk = get_vpk()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        vpk.new(tmpdir).save(out_path)
    except SwapError:
        raise
    except Exception as e:
        raise BuildError(f"Failed to build VPK: {e}") from e
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "packed": packed,
        "material_count": len(material_files or {}),
        "out_path": out_path,
    }


def build_addon_folder(model_files, dst_base, addons_dir, addon_name, material_files=None):
    """
    Write the model (and materials) as a preloader-native extracted addon:
        addons_dir/addon_name/mod.json
        addons_dir/addon_name/models/.../<files>
    This matches what the preloader produces when a VPK is dragged in, so it
    appears ready-to-use without manual import.
    Returns {"addon_dir": path, "packed": [exts], "material_count": n}.
    """
    if ".mdl" not in model_files:
        raise BuildError("No .mdl found in the source model.")

    addon_root = os.path.join(addons_dir, addon_name)
    packed = []
    try:
        os.makedirs(addon_root, exist_ok=True)
        for ext, data in model_files.items():
            if ext == ".mdl":
                data = patch_mdl(data, dst_base)
            out = os.path.join(addon_root, *((dst_base + ext).split("/")))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)
            packed.append(ext)

        for vpk_path, data in (material_files or {}).items():
            out = os.path.join(addon_root, *vpk_path.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)

        manifest = {
            "addon_name": addon_name,
            "type": "Unknown",
            "description": f"Content extracted from {addon_name}.vpk",
            "contents": ["Custom content"],
        }
        with open(os.path.join(addon_root, "mod.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except SwapError:
        raise
    except Exception as e:
        raise BuildError(f"Failed to write addon folder: {e}") from e

    return {
        "addon_dir": addon_root,
        "packed": packed,
        "material_count": len(material_files or {}),
    }


# ---------- weapon build ----------

def build_weapon(view_files, world_files, dst_view_base, dst_world_base, out_path):
    """
    Write a VPK containing both viewmodel and worldmodel sets.
    dst_world_base may be None; world_files may be empty — both handled gracefully
    (viewmodel-only output rather than an error).
    Returns {"packed": [labels...], "out_path": path}.
    """
    if ".mdl" not in view_files:
        raise BuildError("No .mdl found in the source viewmodel.")

    tmpdir = tempfile.mkdtemp()
    packed = []
    try:
        for ext, data in view_files.items():
            if ext == ".mdl":
                data = patch_mdl(data, dst_view_base)
            out = os.path.join(tmpdir, *((dst_view_base + ext).split("/")))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)
            packed.append(f"view{ext}")

        if world_files and dst_world_base:
            for ext, data in world_files.items():
                if ext == ".mdl":
                    data = patch_mdl(data, dst_world_base)
                out = os.path.join(tmpdir, *((dst_world_base + ext).split("/")))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                open(out, "wb").write(data)
                packed.append(f"world{ext}")

        vpk = get_vpk()
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        vpk.new(tmpdir).save(out_path)
    except SwapError:
        raise
    except Exception as e:
        raise BuildError(f"Failed to build weapon VPK: {e}") from e
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {"packed": packed, "out_path": out_path}


def build_weapon_addon_folder(view_files, world_files, dst_view_base, dst_world_base, addons_dir, addon_name):
    """
    Write weapon models as a preloader-native addon folder.
    Writes both model sets at their correct VPK paths inside the addon root:
        addon_root/models/weapons/c_models/...  (viewmodel)
        addon_root/models/weapons/w_models/...  (worldmodel, if present)
        addon_root/mod.json
    This matches what the preloader produces when a weapon VPK is dragged in.
    Returns {"addon_dir": path, "packed": [labels...]}.
    """
    if ".mdl" not in view_files:
        raise BuildError("No .mdl found in the source viewmodel.")

    addon_root = os.path.join(addons_dir, addon_name)
    packed = []
    try:
        os.makedirs(addon_root, exist_ok=True)

        for ext, data in view_files.items():
            if ext == ".mdl":
                data = patch_mdl(data, dst_view_base)
            out = os.path.join(addon_root, *((dst_view_base + ext).split("/")))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(data)
            packed.append(f"view{ext}")

        if world_files and dst_world_base:
            for ext, data in world_files.items():
                if ext == ".mdl":
                    data = patch_mdl(data, dst_world_base)
                out = os.path.join(addon_root, *((dst_world_base + ext).split("/")))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                open(out, "wb").write(data)
                packed.append(f"world{ext}")

        manifest = {
            "addon_name": addon_name,
            "type": "Unknown",
            "description": f"Content extracted from {addon_name}.vpk",
            "contents": ["Custom content"],
        }
        with open(os.path.join(addon_root, "mod.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except SwapError:
        raise
    except Exception as e:
        raise BuildError(f"Failed to write weapon addon folder: {e}") from e

    return {"addon_dir": addon_root, "packed": packed}


def preview_build_weapon(view_files, world_files, dst_view_base, dst_world_base):
    """
    Return a preview of what build_weapon() would produce, without writing anything.
    dst_world_base may be None if world path couldn't be derived.
    """
    entries = []
    for ext, data in view_files.items():
        entries.append({"path": dst_view_base + ext, "ext": f"view{ext}", "size": len(data)})
    for ext, data in (world_files or {}).items():
        if dst_world_base:
            entries.append({"path": dst_world_base + ext, "ext": f"world{ext}", "size": len(data)})
    return {
        "entries": entries,
        "view_count": len(view_files),
        "world_count": len(world_files or {}),
        "total_size": sum(e["size"] for e in entries),
    }


# ---------- mod management ----------

def read_target_stem(vpk_path):
    """Return the lowercased model stem (no extension) inside a built VPK, or None."""
    vpk = get_vpk()
    try:
        pak = vpk.open(vpk_path)
        for p in pak:
            if p.endswith(".mdl"):
                return p[:-4].lower()
    except Exception:
        return None
    return None


def list_output_mods(output_dir):
    """
    List .vpk files we've built in output_dir, including subfolders.
    Returns [{path, name, rel, in_subfolder, target_stem}] sorted by location then name.
    """
    if not os.path.isdir(output_dir):
        return []
    mods = []
    for dirpath, _, filenames in os.walk(output_dir):
        for fn in sorted(filenames):
            if fn.lower().endswith(".vpk"):
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, output_dir)
                mods.append({
                    "path": path,
                    "name": fn,
                    "rel": rel,
                    "in_subfolder": os.path.abspath(dirpath) != os.path.abspath(output_dir),
                    "target_stem": read_target_stem(path),
                })
    return sorted(mods, key=lambda m: (m["in_subfolder"], m["rel"]))


def remove_file(path):
    """Delete a file. Raises SwapError if it doesn't exist."""
    if not os.path.isfile(path):
        raise SwapError(f"File not found: {path}")
    os.remove(path)


def list_preloader_addons(addons_dir, signature):
    """
    List addons present in the preloader's addons folder.
    Returns [{kind, name, rel, is_ours}] where kind is:
      "addon" - a folder containing a mod.json (the preloader's native format)
      "vpk"   - a loose .vpk file (manually placed; may not be recognised)
    Raises SwapError if the folder is missing. Reflects what's present in the
    folder, not which addons are enabled/disabled inside the preloader.
    """
    if not os.path.isdir(addons_dir):
        raise SwapError(f"Preloader addons folder not found: {addons_dir}")

    out = []
    # native addon folders: any dir (at any depth) containing a mod.json
    for root, dirs, files in os.walk(addons_dir):
        if "mod.json" in files:
            name = os.path.basename(root)
            out.append({
                "kind": "addon",
                "name": name,
                "rel": os.path.relpath(root, addons_dir),
                "is_ours": signature.lower() in name.lower(),
            })
            dirs[:] = []  # don't descend into an addon's own contents
    # loose .vpk files
    for root, _, files in os.walk(addons_dir):
        for fn in sorted(files):
            if fn.lower().endswith(".vpk"):
                full = os.path.join(root, fn)
                out.append({
                    "kind": "vpk",
                    "name": fn,
                    "rel": os.path.relpath(full, addons_dir),
                    "is_ours": signature.lower() in fn.lower(),
                })
    return sorted(out, key=lambda a: (a["kind"], a["rel"]))


# ---------- dry run / preview ----------

def preview_build(model_files, dst_base, material_files=None):
    """
    Return a preview of what build() would produce, without writing anything.
    Useful for dry-run checks and GUI preview panes.
    """
    entries = []
    for ext, data in model_files.items():
        entries.append({"path": dst_base + ext, "ext": ext, "size": len(data)})
    for vpk_path, data in (material_files or {}).items():
        entries.append({"path": vpk_path, "ext": "material", "size": len(data)})
    return {
        "entries": entries,
        "model_count": len(model_files),
        "material_count": len(material_files or {}),
        "total_size": sum(e["size"] for e in entries),
    }
