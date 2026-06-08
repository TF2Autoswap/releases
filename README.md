# TF2autoswap Version 4.5

Swap any Team Fortress 2 cosmetic or weapon model for another, on your own computer only.

The tool creates a file that works with the [Casual Preloader](https://cueki.github.io/casual-pre-loader/) by cukei.

---

## What this tool does

- You choose two items — one to **replace**, and one to **use as the replacement**
- The tool swaps the model files and builds an output file
- Only you see the change — other players see the original item
- No game files are permanently changed

---

## Requirements

- **Python 3.8 or later** — [python.org/downloads](https://www.python.org/downloads/)
- The `vpk` library — installed automatically on first run
- **Optional:** the `vdf` library — installed automatically if needed. Enables friendly item names and safety warnings.

---

## Files

Keep all three files in the same folder:

| File | Required | Purpose |
|---|---|---|
| `tf2autoswap.py` | Yes | Run this file to use the tool |
| `tf2_core.py` | Yes | Core logic — do not delete |
| `tf2_schema.py` | Optional | Friendly item names and warnings |

Built mods and a log file (`tf2autoswap.log`) are saved inside the tool folder itself:

```
tf2autoswap/
  tf2autoswap.py
  tf2_core.py
  tf2_schema.py
  output/           ← built VPKs saved here
  tf2autoswap.log   ← errors and build history
```

This keeps everything self-contained. To move or share the tool, zip the whole folder.

---

## How to run

Open a terminal in the folder containing the files, then run:

```
python3 tf2autoswap.py
```

This opens the menu. No extra steps are needed for basic use.

---

## Menu options

The menu has four options:

1. **Create a cosmetic swap** — swap hats, miscs, and other wearable items
2. **Create a weapon swap** — swap weapon models (viewmodel and worldmodel)
3. **List / remove mods I've made** — view and delete your built mods
4. **List addons in the preloader folder** — see what is installed in the preloader

---

## Cosmetic swap — step by step

1. **Class** — choose which class the item belongs to
2. **Item to replace** — search for the item you want to replace
3. **Replacement source** — search for the item to use as the replacement, or import a file from your computer
4. **Confirm** — review the swap. Warnings are shown here if there is a risk of clipping.
5. **Output** — choose where to save the result

---

## Weapon swap — step by step

1. **Class** — choose which class the weapon belongs to
2. **Loadout slot** — choose the slot (primary, secondary, melee, etc.)
3. **Weapon to replace** — search for the weapon you want to replace
4. **Replacement source** — search for the weapon to use as the replacement
5. **Confirm and output** — review the swap, then choose where to save

The tool swaps both the **viewmodel** (what you see in first person) and the **worldmodel** (what other players see) in one step.

---

## Warnings

The tool shows a warning at the confirm step if a swap may cause a visual problem.

| Warning type | What it means |
|---|---|
| Head clip warning | The replacement model hides the head, but the target slot does not. The default head will show through. |
| Equip region mismatch | The two items cover different areas of the player model. The swap may clip with other equipped items. |
| Slot mismatch warning | The two weapons are from different loadout slots. This may cause animation problems in-game. |
| Preloader write warning | Shown before writing directly to the preloader folder. Requires typing `yes` to confirm. Saving a VPK and importing manually is the safer option. |

You can still proceed past most warnings. It is your choice.

---

## Searching for items

Search uses the internal file name (called a keyword) for each item.

Searching is flexible:
- Spaces and underscores both work — searching `hot air` finds `hot_air`
- Typos get a "did you mean" suggestion

If you need to find a keyword manually, use **backpack.tf**:

1. Go to `https://backpack.tf/overview/Item Name`
2. Find the line that says **Player model defined as** — the keyword is the file name shown there

---

## Friendly item names

If `tf2_schema.py` and the `vdf` library are both present, the tool reads TF2's item database (`items_game.txt`) and shows:

- Real item names — for example "The Scattergun" instead of `c_scattergun`
- Slot labels — for example `[primary]` next to weapon names
- `[replaces head]` tag on cosmetics that replace the player's head

If the file or library is missing, the tool continues without these features.

---

## Importing a custom model

You can use a model file downloaded from a site like Gamebanana instead of a built-in TF2 item.

**In interactive mode:** choose "Import a model from disk" at the source step.

**On the command line:**

```
python3 tf2autoswap.py --import ~/Downloads/mymod/models/player/items/pyro/myhat.mdl targetkeyword
```

The tool automatically includes any `materials/` folder found next to the model folder, so custom textures are bundled too.

---

## Output formats

When you save a mod, you choose the destination. The format is chosen automatically.

| Destination | Output format |
|---|---|
| Output folder or custom path | A single `.vpk` file — good for sharing or manual import |
| Preloader addons folder | A folder with extracted files and a `mod.json` — ready to enable in the preloader with no extra steps |

Output files are saved to the `output/` folder inside the tool folder, with this name format:

```
<Target> replacement mod (<Source>)_TF2autoswap.vpk
```

---

## Installing a mod in the Casual Preloader

1. Open the Casual Preloader
   - Linux: run `./scripts/run.sh`
   - Windows: run `RUNME.bat`
2. Drag your `.vpk` file onto the preloader window
3. In the Addons tab, tick your mod. Untick any other mod that uses the same slot.
4. Click **Install**
5. Launch TF2

---

## Command line options

```
python3 tf2autoswap.py <source> <target> [options]
```

| Option | Description |
|---|---|
| `source` | Keyword of the item to use as the replacement |
| `target` | Keyword of the item to replace |
| `--weapon` | Swap weapons instead of cosmetics |
| `--filter CLASS` | Filter results to one class (example: `pyro`) |
| `--import PATH` | Use a local `.mdl` file as the replacement |
| `--out PATH` | Set a custom output path (file or folder) |
| `--to-preloader` | Save directly to the preloader addons folder |
| `--dry-run` | Preview what would be built, without saving anything |
| `--list` | Search for items without building anything |
| `--list --weapon` | Search for weapons without building anything |
| `--list-mods` | List the mods you have built |
| `--list-installed` | List addons in the preloader folder |
| `--preloader PATH` | Set the path to the preloader addons folder |
| `--tf2 PATH` | Set the path to your TF2 `tf/` folder |
| `--version` | Show the current version number |

---

## Notes

- Only one replacement per slot can be active at a time
- Re-run the preloader install step after any TF2 update
- Changes are client-side only — other players see the original item
- `--list-installed` shows what files are present in the preloader folder. It does not show which addons are currently enabled or disabled inside the preloader — that is stored in the preloader's own settings.

---

## License

This project is licensed under **Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0)**.

- Free to use and modify
- Credit must be given
- Resale is not permitted

---

## Credits

- Tool built by **Sky (TF2Autoswap)** with coding assistance from Claude (Anthropic)
- Casual Preloader by **cukei** — [gamebanana.com/tools/19049](https://gamebanana.com/tools/19049)
