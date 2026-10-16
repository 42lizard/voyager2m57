#!/usr/bin/env python3
"""Convert Oryx Voyager C exports to a BORNE M57 Vial layout (protocol 6)."""
# SPDX-License-Identifier: GPL-2.0-only
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor' / 'vial_gui'))
from keycodes.keycodes import Keycode, recreate_keyboard_keycodes

M57_UID = 5010774632021243529
POSITIONS = []
for row in range(4):
    POSITIONS.extend((row, col) for col in range(6))
    POSITIONS.extend((row + 5, col) for col in range(1, 7))
POSITIONS.extend([(4, 4), (4, 5), (9, 1), (9, 2)])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def split_args(text):
    args, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            require(depth >= 0, 'Unbalanced keycode expression')
        elif char == ',' and depth == 0:
            args.append(text[start:i].strip())
            start = i + 1
    require(depth == 0, 'Unbalanced keycode expression')
    if text[start:].strip():
        args.append(text[start:].strip())
    return args


def balanced(text, start, opening='(', closing=')'):
    """Read content after an already consumed opening delimiter."""
    depth = 1
    for end in range(start, len(text)):
        if text[end] == opening:
            depth += 1
        elif text[end] == closing:
            depth -= 1
        if depth == 0:
            return text[start:end]
    raise ValueError(f'Unclosed {opening} in exported source')


def source_directory(path):
    if path.is_file() and path.name == 'keymap.c':
        return path.parent
    if (path / 'keymap.c').is_file():
        return path
    candidates = list(path.glob('*/keymap.c'))
    require(len(candidates) == 1, 'Source must contain exactly one Voyager keymap.c')
    return candidates[0].parent


def convert(source_path, template):
    source_path = source_directory(Path(source_path))
    raw = (source_path / 'keymap.c').read_text()
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', raw, flags=re.S)
    require(template.get('vial_protocol') == 6, 'Only Vial protocol 6 is supported')
    require(template.get('uid') == M57_UID, 'Template is not the supported BORNE M57 UID')
    layout = template.get('layout', [])
    require(1 <= len(layout) <= 16, 'Template needs 1–16 layers')
    for layer in layout:
        require(len(layer) == 10 and all(len(row) == 7 for row in layer), 'M57 matrix must be 10×7')
        require(all(layer[r][c] != -1 for r, c in POSITIONS), 'Template has missing Voyager positions')
    result = copy.deepcopy(template)
    dances = result.get('tap_dance', [])
    combos = result.get('combo', [])
    require(all(len(d) == 5 for d in dances + combos), 'Invalid tap-dance/combo entry size')
    recreate_keyboard_keycodes(SimpleNamespace(vial_protocol=6, layers=len(layout),
        macro_count=len(result.get('macro', [])), tap_dance_count=len(dances),
        custom_keycodes=None, midi='off', supported_features=set()))
    warnings = []
    aliases = {'KC_LEFT_SHIFT': 'KC_LSHIFT', 'KC_PAGE_UP': 'KC_PGUP'}
    i18n = source_path / 'i18n.h'
    if i18n.exists():
        aliases.update(re.findall(r'^#define\s+(\w+)\s+([^\n]+)', i18n.read_text(), re.M))
    dance_slots, dual_slots = {}, {}

    def keycode(expression):
        expression = expression.strip()
        if expression == 'TOGGLE_LAYER_COLOR':
            warning = 'TOGGLE_LAYER_COLOR replaced with KC_NO; Oryx RGB callbacks are not portable.'
            if warning not in warnings:
                warnings.append(warning)
            return 'KC_NO'
        if expression in dual_slots:
            return f'TD({dual_slots[expression]})'
        expression = re.sub(r'DANCE_\d+', lambda m: str(dance_slots[m[0]]), expression)
        for _ in range(20):
            expanded = re.sub(r'\b\w+\b', lambda m: aliases.get(m[0], m[0]), expression)
            if expanded == expression:
                break
            expression = expanded
        else:
            raise ValueError('Recursive i18n alias')
        try:
            value = Keycode.deserialize(expression, reraise=True)
        except Exception as exc:
            raise ValueError(f'Unsupported keycode: {expression}') from exc
        require(isinstance(value, int) and 0 <= value <= 65535, f'Invalid keycode: {expression}')
        # Vial's codec masks layer arguments; validate before that can hide errors.
        for match in re.finditer(r'\b(?:LT|MO|TO|TG|DF|OSL|TT)\(\s*(\d+)', expression):
            require(int(match[1]) < len(layout), f'Layer out of range: {expression}')
        return Keycode.serialize(value)

    def allocate(entries, label, count):
        free = [i for i, entry in enumerate(entries)
                if all(Keycode.deserialize(k, reraise=True) == 0 for k in entry[:4 if label == 'tap-dance' else 5])]
        require(len(free) >= count, f'Need {count} free {label} slots, found {len(free)}')
        return free[:count]

    layer_matches = list(re.finditer(r'\[(\d+)\]\s*=\s*LAYOUT_voyager\(', source))
    require(layer_matches, 'No LAYOUT_voyager layers found')
    require([int(m[1]) for m in layer_matches] == list(range(len(layer_matches))),
            'Voyager layers must be contiguous, starting at 0')
    require(len(layer_matches) <= len(layout), 'Template has too few layers')
    layers = [split_args(balanced(source, m.end())) for m in layer_matches]
    require(all(len(layer) == 52 for layer in layers), 'Each Voyager layer must have 52 keys')
    used = '\n'.join(key for layer in layers for key in layer)
    dance_ids = sorted(set(re.findall(r'\bDANCE_\d+\b', used)), key=lambda s: int(s[6:]))
    dual_ids = sorted(set(re.findall(r'\bDUAL_FUNC_\d+\b', used)), key=lambda s: int(s[10:]))
    free_dances = allocate(dances, 'tap-dance', len(dance_ids) + len(dual_ids))
    dance_slots.update(zip(dance_ids, free_dances))
    dual_slots.update(zip(dual_ids, free_dances[len(dance_ids):]))

    config_file = source_path / 'config.h'
    config = config_file.read_text() if config_file.exists() else ''
    config = re.sub(r'/\*.*?\*/|//[^\n]*', '', config, flags=re.S)

    def number(name, default):
        match = re.search(rf'^\s*#define\s+{name}\b([^\n]*)', config, re.M)
        if not match:
            return default
        require(match[1].strip().isdigit(), f'{name} must be an integer literal')
        value = int(match[1])
        require(0 <= value <= 65535, f'{name} out of range')
        return value

    tapping = number('TAPPING_TERM', 200)
    dual_report = []
    for name, slot in dance_slots.items():
        i = name[6:]
        match = re.search(rf'void dance_{i}_finished\([^;{{]+\)\s*\{{', source)
        require(match is not None, f'Missing finished callback for {name}')
        body = balanced(source, match.end(), '{', '}')
        actions = {}
        for action, expression in re.findall(
                r'case (SINGLE_TAP|SINGLE_HOLD|DOUBLE_TAP|DOUBLE_HOLD):\s*register_code16\((.*?)\);\s*break;', body):
            actions[action] = keycode(expression)
        require('SINGLE_TAP' in actions and 'DOUBLE_TAP' in actions,
                f'{name}: unsupported Oryx tap-dance callback')
        # Transparent is an explicit no-op; KC_NO triggers Vial's tap fallback.
        dances[slot] = [actions['SINGLE_TAP'], actions.get('SINGLE_HOLD', 'KC_TRNS'),
                       actions['DOUBLE_TAP'], actions.get('DOUBLE_HOLD', 'KC_TRNS'), tapping]
    for name, slot in dual_slots.items():
        match = re.search(rf'case {name}:(.*?)return false;', source, re.S)
        require(match is not None, f'Missing custom handler for {name}')
        body = match[1]
        pressed = re.findall(r'(?<!un)register_code16\((.*?)\);', body)
        released = re.findall(r'unregister_code16\((.*?)\);', body)
        require(len(pressed) == 2 and released == pressed and
                re.search(r'if\s*\(record->tap.count\s*>\s*0\)', body),
                f'{name}: expected Oryx tap/hold register/unregister handler')
        tap, hold = map(keycode, pressed)
        dances[slot] = [tap, hold, 'KC_NO', 'KC_NO', tapping]
        dual_report.append({'source': name, 'slot': slot, 'tap': tap, 'hold': hold})

    for index, keys in enumerate(layers):
        for (row, col), expression in zip(POSITIONS, keys):
            result['layout'][index][row][col] = keycode(expression)

    combo_matches = [split_args(balanced(source, m.end()))
                     for m in re.finditer(r'\bCOMBO\(', source)]
    require(all(len(args) == 2 for args in combo_matches), 'Malformed COMBO definition')
    require(not re.search(r'\bCOMBO_ACTION\s*\(', source), 'Custom combo callbacks are not supported')
    require(number('COMBO_COUNT', len(combo_matches)) == len(combo_matches),
            'COMBO_COUNT does not match parsed combos')
    free_combos = allocate(combos, 'combo', len(combo_matches))
    for slot, (name, output) in zip(free_combos, combo_matches):
        match = re.search(rf'\b{re.escape(name)}\[\]\s*=\s*\{{(.*?),\s*COMBO_END\s*\}}', source)
        require(match is not None, f'Missing combo array {name}')
        keys = [keycode(k) for k in split_args(match[1])]
        require(2 <= len(keys) <= 4, 'Vial combos need 2–4 keys')
        combos[slot] = keys + ['KC_NO'] * (4-len(keys)) + [keycode(output)]

    settings = {'7': tapping, '25': number('QUICK_TAP_TERM', tapping),
                '27': number('FLOW_TAP_TERM', 0)}
    for setting, name in [('22', 'PERMISSIVE_HOLD'), ('23', 'HOLD_ON_OTHER_KEY_PRESS'),
                          ('24', 'RETRO_TAPPING'), ('26', 'CHORDAL_HOLD')]:
        settings[setting] = int(bool(re.search(rf'^\s*#define\s+{name}\b', config, re.M)))
    require(all(s in result.get('settings', {}) for s in settings),
            'Template lacks required dynamic timing settings; export from current M57 firmware')
    result['settings'].update(settings)
    # Validate the complete output, including preserved parts, using Vial's codec.
    all_keys = [k for layer in result['layout'] for row in layer for k in row if k != -1]
    all_keys += [k for entry in dances for k in entry[:4]]
    all_keys += [k for entry in combos for k in entry]
    for value in all_keys:
        Keycode.deserialize(value, reraise=True)
    warnings.extend([
        'Oryx RGB callbacks, timeouts and device modules are not transferred.',
        'Custom tap/hold actions use Vial Tap Dance; interruption and timing behavior can differ.',
        'Timing defaults not defined in config.h assume TAPPING_TERM=200 ms and standard QMK defaults.',
        'Not hardware-tested. Keep the template backup before importing in Vial.',
    ])
    report = {'layers_mapped': len(layers), 'keys_per_layer': 52,
              'tap_dance_slots': dance_slots, 'dual_functions': dual_report,
              'combo_slots': free_combos, 'settings': settings, 'warnings': warnings}
    return result, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Oryx export directory or keymap.c')
    parser.add_argument('--template', required=True, type=Path, help='Current M57 .vil backup')
    parser.add_argument('--output', required=True, type=Path, help='New .vil file (must not exist)')
    args = parser.parse_args()
    report_path = args.output.with_suffix('.report.json')
    try:
        require(args.output.suffix == '.vil', 'Output must end in .vil')
        require(not args.output.exists() and not report_path.exists(), 'Output or report already exists; choose a new filename')
        template_bytes = args.template.read_bytes()
        result, report = convert(args.source, json.loads(template_bytes))
        payload = json.dumps(result, indent=2) + '\n'
        report['template_sha256'] = hashlib.sha256(template_bytes).hexdigest()
        report['output_sha256'] = hashlib.sha256(payload.encode()).hexdigest()
        with args.output.open('x') as file:
            file.write(payload)
        with report_path.open('x') as file:
            json.dump(report, file, indent=2)
            file.write('\n')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(f'Created {args.output} ({report["layers_mapped"]} layers). Report: {report_path}')
    for warning in report['warnings']:
        print(f'Note: {warning}')


if __name__ == '__main__':
    main()
