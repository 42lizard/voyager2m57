# voyager2m57

Convert an **Oryx Voyager source export** into an importable **BORNE M57 Vial
layout**, using your existing `.vil` backup as the device template. No firmware
build, keyboard connection or flashing is needed.

This is a focused converter for Oryx's generated `LAYOUT_voyager` C format and
the M57's 10×7 matrix. It is not a general C interpreter or a converter for
arbitrary QMK keyboards. It was checked against a six-layer Voyager export;
keycodes and file structure are validated, but hardware behavior still needs testing.

## Install and run

Python **3.10 or newer** and Git are required. On macOS or Linux:

```sh
git clone https://github.com/42lizard/voyager2m57.git
cd voyager2m57
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt

.venv/bin/python voyager2m57.py /path/to/oryx-source-export \
  --template /path/to/current-m57.vil \
  --output /path/to/voyager-m57.vil
```

Download **source code** from Oryx and extract it first. `source` accepts the
export directory, its single nested source directory, or `keymap.c` itself.
Keep the accompanying `i18n.h` and `config.h` beside it.

Use a fresh backup from the M57 running the firmware you intend to use.
Supported device UID: `89 36 2A C7 FA D8 89 45`, Vial protocol 6. The template
must expose dynamic timing settings, including Flow Tap and Chordal Hold.

The command creates `voyager-m57.vil` and `voyager-m57.report.json`. Read the
report's warnings, then import the `.vil` in **Vial → File → Load layout**.
Keep the original backup so you can restore it. Existing output files are
never overwritten. Conversion runs offline once dependencies are installed.

## Mapping and preservation

The Voyager has 52 keys. Each row's six left and six right keys map to the
corresponding outer M57 columns. Thumb mapping is fixed:

| Voyager position, left to right | M57 matrix position |
| --- | --- |
| Left thumb 1 | `[4,4]` |
| Left thumb 2 | `[4,5]` |
| Right thumb 1 | `[9,1]` |
| Right thumb 2 | `[9,2]` |

Extra M57 keys, encoders, layers beyond the imported layer count, macros,
device metadata and other template data are preserved. Original tap dances
and combos remain in their slots; imported ones use empty slots. Insufficient
capacity, a wrong device, unknown keycodes and invalid layer references stop
conversion. Start each repeat conversion from your original template to avoid
accumulating duplicate tap dances and combos.

Supported export constructs:

- Contiguous numeric layers starting at 0, with 52 keys per layer.
- Standard keys, modifiers, layer taps, mod taps and `i18n.h` aliases.
- Oryx `DANCE_n` callbacks with explicit single/double tap and optional hold
  actions using `register_code16`.
- Oryx `DUAL_FUNC_n` handlers with a tap/hold branch and paired
  `register_code16`/`unregister_code16` calls, translated to Vial Tap Dance.
- Direct `COMBO(name, output)` definitions with two to four input keys.
- Literal timing settings in `config.h`: Tapping Term, Quick Tap Term,
  Flow Tap, Permissive Hold, Hold on Other Key Press, Retro Tapping and Chordal Hold.

## Differences to Oryx

- Custom tap/hold actions use Vial Tap Dance. Their interruption and rollover
  behavior can differ from Oryx's custom layer-tap handling. Flow Tap and
  Chordal Hold do not make those replacement actions behave identically.
- Absent hold actions in original tap dances use `KC_TRNS` as an explicit
  no-op, because Vial treats `KC_NO` as a request to fall back to the tap action.
- Layer colors, RGB callbacks/timeouts, Navigator/Automouse modules and other
  custom firmware logic are not transferred. `TOGGLE_LAYER_COLOR` becomes
  `KC_NO` with a report warning. Other unrecognized keycodes fail conversion.
- This parses the documented Oryx generator patterns, not arbitrary callbacks.
  Modified C logic in callbacks must be reviewed separately. Custom combo
  callbacks (`COMBO_ACTION`) are rejected.
- When the export omits timing values, the converter assumes a 200 ms tapping
  term, Quick Tap equal to Tapping Term, Flow Tap off, and unlisted hold flags
  off. Defaults hidden inside ZSA modules cannot be inferred from this export.
- German aliases are translated into their HID keycodes. Keep the appropriate
  host input language; the converter does not change macOS/Windows layouts.

## Tests

```sh
.venv/bin/python -m unittest -v
```

Tests use synthetic exports and cover matrix/thumb mapping, modifiers, custom
actions, free-slot allocation, preservation, rejected inputs and repeatable CLI
output. No personal keymaps or backups are published.

## Sources and license

The original code and documentation of voyager2m57 are licensed under
**GPL-2.0-only** (GNU General Public License version 2 only); see [LICENSE](LICENSE).
The combined project is distributed under GPL version 2.

The vendored Vial GUI files retain their upstream **GPL-2.0-or-later** license
and notices; this project uses their GPL version 2 option. The official codec
is included at a pinned commit to avoid inventing keycode translations. See
[vendor/README.md](vendor/README.md) for provenance and hashes.

- [Vial Tap Dance](https://get.vial.today/manual/tap-dance.html)
- [Vial runtime tap-dance behavior](https://github.com/vial-kb/vial-qmk/blob/00fc4627cd038ac9b7e9b8bf2b40b50e9e88aecb/quantum/vial.c)
- [Vial timing setting IDs](https://github.com/vial-kb/vial-qmk/blob/00fc4627cd038ac9b7e9b8bf2b40b50e9e88aecb/quantum/qmk_settings.c)
- [M57 firmware](https://github.com/42lizard/borne-m57-firmware)
