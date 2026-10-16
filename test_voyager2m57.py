"""Small synthetic exports: no personal layouts are needed for the tests."""
# SPDX-License-Identifier: GPL-2.0-only
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from voyager2m57 import convert, M57_UID, POSITIONS


def template():
    layer = [['KC_NO'] * 7 for _ in range(10)]
    for r, cols in [(0, [6]), (4, [0, 1, 2, 6]), (5, [0]), (9, [0, 4, 5, 6])]:
        for c in cols:
            layer[r][c] = -1
    layer[1][6] = 'KC_UP'
    return {'version': 1, 'uid': M57_UID, 'vial_protocol': 6, 'via_protocol': 9,
            'layout': [copy.deepcopy(layer), copy.deepcopy(layer)],
            'encoder_layout': [[['KC_VOLD', 'KC_VOLU']]] * 2,
            'macro': [[]], 'settings': {str(i): 0 for i in [7, 22, 23, 24, 25, 26, 27]},
            'tap_dance': [['KC_ESCAPE', 'KC_NO', 'KC_NO', 'KC_NO', 200]] +
                         [['KC_NO'] * 4 + [200] for _ in range(3)],
            'combo': [['KC_A', 'KC_B', 'KC_NO', 'KC_NO', 'KC_C'], ['KC_NO'] * 5]}


def export(path):
    keys = ['KC_A'] * 52
    keys[0] = 'TD(DANCE_3)'
    keys[1] = 'DUAL_FUNC_7'
    keys[6] = 'DE_Z'
    keys[12] = 'MT(MOD_LALT | MOD_LCTL | MOD_LGUI, KC_A)'
    keys[48:] = ['LT(1, KC_ENTER)', 'KC_TAB', 'KC_BSPC', 'KC_SPACE']
    text = '[0] = LAYOUT_voyager(' + ', '.join(keys) + ');\n'
    text += '''
void dance_3_finished(tap_dance_state_t *state, void *user_data) {
    switch (dance_state[3].step) {
        case SINGLE_TAP: register_code16(KC_ESCAPE); break;
        case DOUBLE_TAP: register_code16(DE_CIRC); break;
        case DOUBLE_SINGLE_TAP: tap_code16(KC_ESCAPE); register_code16(KC_ESCAPE);
    }
}
bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    switch (keycode) {
    case DUAL_FUNC_7:
        if (record->tap.count > 0) {
            if (record->event.pressed) { register_code16(KC_S); }
            else { unregister_code16(KC_S); }
        } else {
            if (record->event.pressed) { register_code16(LCTL(KC_SPACE)); }
            else { unregister_code16(LCTL(KC_SPACE)); }
        }
        return false;
    }
}
const uint16_t PROGMEM combo0[] = { MT(MOD_RALT, KC_J), MT(MOD_RCTL, KC_K), COMBO_END};
combo_t key_combos[] = { COMBO(combo0, LCTL(KC_ESCAPE)) };
'''
    (path / 'keymap.c').write_text(text)
    (path / 'i18n.h').write_text('#define DE_Z KC_Y\n#define DE_CIRC KC_GRV\n')
    (path / 'config.h').write_text('#define FLOW_TAP_TERM 100\n#define PERMISSIVE_HOLD\n'
                                  '#define CHORDAL_HOLD\n#define TAPPING_TERM 180\n#define COMBO_COUNT 1\n')


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        export(self.path)
        self.base = template()

    def test_convert_preserves_extras_and_uses_free_slots(self):
        before = copy.deepcopy(self.base)
        out, report = convert(self.path, self.base)
        self.assertEqual(self.base, before)
        self.assertEqual(out['layout'][0][0][0], 'TD(1)')
        self.assertEqual(out['layout'][0][0][1], 'TD(2)')
        self.assertEqual(out['layout'][0][5][1], 'KC_Y')
        self.assertEqual(out['layout'][0][1][0], 'LCAG_T(KC_A)')
        self.assertEqual(out['layout'][0][4][4], 'LT1(KC_ENTER)')
        self.assertEqual(out['layout'][0][9][1], 'KC_BSPACE')
        self.assertEqual(out['tap_dance'][1], ['KC_ESCAPE', 'KC_TRNS', 'KC_GRAVE', 'KC_TRNS', 180])
        self.assertEqual(out['tap_dance'][2], ['KC_S', 'LCTL(KC_SPACE)', 'KC_NO', 'KC_NO', 180])
        self.assertEqual(out['tap_dance'][0], before['tap_dance'][0])
        self.assertEqual(out['combo'][0], before['combo'][0])
        self.assertEqual(out['combo'][1], ['RALT_T(KC_J)', 'RCTL_T(KC_K)', 'KC_NO', 'KC_NO', 'LCTL(KC_ESCAPE)'])
        self.assertEqual(out['encoder_layout'], before['encoder_layout'])
        self.assertEqual(out['settings']['27'], 100)
        self.assertEqual(out['settings']['23'], 0)
        for layer in range(2):
            for row in range(10):
                for col in range(7):
                    if layer > 0 or (row, col) not in POSITIONS:
                        self.assertEqual(out['layout'][layer][row][col], before['layout'][layer][row][col])
        self.assertEqual(report['layers_mapped'], 1)

    def test_wrong_device_and_capacity_fail(self):
        for change, message in [({'uid': 1}, 'UID'), ({'vial_protocol': 5}, 'protocol'),
                                ({'tap_dance': []}, 'free tap-dance'), ({'combo': []}, 'free combo')]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                convert(self.path, self.base | change)

    def test_unknown_keycode_and_layer_fail(self):
        p = self.path / 'keymap.c'
        text = p.read_text()
        for key, message in [('UNSUPPORTED_CUSTOM_KEY', 'Unsupported keycode'), ('LT(9, KC_ENTER)', 'Layer out of range')]:
            p.write_text(text.replace('LT(1, KC_ENTER)', key))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                convert(self.path, self.base)

    def test_custom_combo_callback_is_rejected(self):
        p = self.path / 'keymap.c'
        p.write_text(p.read_text().replace('COMBO(combo0, LCTL(KC_ESCAPE))', 'COMBO_ACTION(combo0)'))
        with self.assertRaisesRegex(ValueError, 'Custom combo'):
            convert(self.path, self.base)

    def test_bad_matrix_and_source_fail(self):
        self.base['layout'][0][0][0] = -1
        with self.assertRaisesRegex(ValueError, 'missing Voyager positions'):
            convert(self.path, self.base)
        (self.path / 'keymap.c').write_text('[0] = LAYOUT_voyager(KC_A')
        with self.assertRaisesRegex(ValueError, 'Unclosed'):
            convert(self.path, template())

    def test_cli_is_repeatable_and_never_overwrites(self):
        base = self.path / 'base.vil'
        base.write_text(json.dumps(self.base))
        output = self.path / 'out.vil'
        command = [sys.executable, str(Path(__file__).with_name('voyager2m57.py')),
                   str(self.path), '--template', str(base), '--output', str(output)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        payload = output.read_bytes()
        self.assertEqual(json.loads(base.read_text()), self.base)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(output.read_bytes(), payload)
        command[-1] = str(self.path / 'second.vil')
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual((self.path / 'second.vil').read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
