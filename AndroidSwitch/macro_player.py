#!/usr/bin/env python3
"""
HID report helpers and macro sequence for civswitch.py.

The session configures USB, starts neutral reports, plays the macro and restores
Android USB. Run it through npm run test or npm run start.
"""

import struct
import time

# ---------------------------------------------------------------------------
# HID keycodes (USB HID Usage Tables — matches TinyUSB HID_KEY_*)
# ---------------------------------------------------------------------------
HID_KEY_A           = 0x04
HID_KEY_Z           = 0x1D
HID_KEY_1           = 0x1E
HID_KEY_0           = 0x27
HID_KEY_ENTER       = 0x28
HID_KEY_ESCAPE      = 0x29
HID_KEY_BACKSPACE   = 0x2A
HID_KEY_TAB         = 0x2B
HID_KEY_SPACE       = 0x2C
HID_KEY_MINUS       = 0x2D
HID_KEY_EQUAL       = 0x2E
HID_KEY_BRACKET_LEFT  = 0x2F
HID_KEY_BRACKET_RIGHT = 0x30
HID_KEY_BACKSLASH   = 0x31
HID_KEY_SEMICOLON   = 0x33
HID_KEY_APOSTROPHE  = 0x34
HID_KEY_GRAVE       = 0x35
HID_KEY_COMMA       = 0x36
HID_KEY_PERIOD      = 0x37
HID_KEY_SLASH       = 0x38

MOD_NONE   = 0x00
MOD_LSHIFT = 0x02

# Switch USB gamepad button masks
SWITCH_USB_MASK_A    = (1 << 2)
SWITCH_USB_HAT_NOTHING = 0x08
SWITCH_USB_JOYSTICK_MID = 0x80

# ---------------------------------------------------------------------------
# Timings — retain the values tested with the Android USB transport
# ---------------------------------------------------------------------------
KEY_HOLD_MS       = 32
KEY_GAP_MS        = 32
ENTER_HOLD_MS     = 32
ENTER_GAP_MS      = 200
PRE_A_WAIT_MS     = 750
POST_A_WAIT_MS    = 550
A_PRESS_MS        = 50
PREAMBLE_A_COUNT  = 5
PREAMBLE_GAP_MS   = 550
ESC_TO_A_WAIT_MS  = 750

# ---------------------------------------------------------------------------
# ASCII -> (needs_shift, hid_keycode)
# ---------------------------------------------------------------------------
ASCII_TO_KEY = {' ': (0, HID_KEY_SPACE), '\t': (0, HID_KEY_TAB)}
for _i, _c in enumerate('abcdefghijklmnopqrstuvwxyz'):
    ASCII_TO_KEY[_c] = (0, HID_KEY_A + _i)
    ASCII_TO_KEY[_c.upper()] = (1, HID_KEY_A + _i)
for _i, _c in enumerate('1234567890'):
    ASCII_TO_KEY[_c] = (0, HID_KEY_1 + _i)
ASCII_TO_KEY.update({
    '!': (1, HID_KEY_1), '@': (1, HID_KEY_1+1), '#': (1, HID_KEY_1+2),
    '$': (1, HID_KEY_1+3), '%': (1, HID_KEY_1+4), '^': (1, HID_KEY_1+5),
    '&': (1, HID_KEY_1+6), '*': (1, HID_KEY_1+7), '(': (1, HID_KEY_1+8),
    ')': (1, HID_KEY_0),
    '-': (0, HID_KEY_MINUS),    '_': (1, HID_KEY_MINUS),
    '=': (0, HID_KEY_EQUAL),    '+': (1, HID_KEY_EQUAL),
    '[': (0, HID_KEY_BRACKET_LEFT),  '{': (1, HID_KEY_BRACKET_LEFT),
    ']': (0, HID_KEY_BRACKET_RIGHT), '}': (1, HID_KEY_BRACKET_RIGHT),
    '\\': (0, HID_KEY_BACKSLASH), '|': (1, HID_KEY_BACKSLASH),
    ';': (0, HID_KEY_SEMICOLON),  ':': (1, HID_KEY_SEMICOLON),
    "'": (0, HID_KEY_APOSTROPHE), '"': (1, HID_KEY_APOSTROPHE),
    '`': (0, HID_KEY_GRAVE),     '~': (1, HID_KEY_GRAVE),
    ',': (0, HID_KEY_COMMA),     '<': (1, HID_KEY_COMMA),
    '.': (0, HID_KEY_PERIOD),    '>': (1, HID_KEY_PERIOD),
    '/': (0, HID_KEY_SLASH),     '?': (1, HID_KEY_SLASH),
})


# ---------------------------------------------------------------------------
# Low-level HID report helpers
# ---------------------------------------------------------------------------

def kbd_report(modifier=0, key=0):
    """8-byte boot-protocol keyboard report."""
    return struct.pack('BBBBBBBB', modifier, 0, key, 0, 0, 0, 0, 0)


def pad_report(buttons=0, hat=SWITCH_USB_HAT_NOTHING,
               lx=SWITCH_USB_JOYSTICK_MID, ly=SWITCH_USB_JOYSTICK_MID,
               rx=SWITCH_USB_JOYSTICK_MID, ry=SWITCH_USB_JOYSTICK_MID):
    """8-byte SwitchUsbReport: buttons(u16 LE), hat, lx, ly, rx, ry, vendor."""
    return struct.pack('<HBBBBBB', buttons, hat, lx, ly, rx, ry, 0)


KBD_RELEASED = kbd_report()
PAD_NEUTRAL  = pad_report()



def sleep_ms(ms):
    if ms > 0:
        time.sleep(ms / 1000.0)


# ---------------------------------------------------------------------------
# Macro playback
# ---------------------------------------------------------------------------

def play_payload(hid, lines, keyboard_only=False):
    """Play the full macro sequence for the supplied chat lines."""

    total_chars = sum(len(l) for l in lines)
    print(f"Playing {len(lines)} batch(es), {total_chars} chars total")

    # Preamble: gamepad A x5
    if not keyboard_only:
        print("  Preamble: pressing A x5...")
        for i in range(PREAMBLE_A_COUNT):
            hid.send_pad(buttons=SWITCH_USB_MASK_A)
            sleep_ms(A_PRESS_MS)
            hid.release_pad()
            sleep_ms(PREAMBLE_GAP_MS)

    for batch_idx, line in enumerate(lines):
        pct = (batch_idx + 1) * 100 // len(lines)
        preview = line[:60] + ('...' if len(line) > 60 else '')
        print(f"  [{pct:3d}%] Batch {batch_idx+1}/{len(lines)}: {preview}")

        # Press Esc
        hid.send_kbd(0, HID_KEY_ESCAPE)
        sleep_ms(KEY_HOLD_MS)
        hid.release_kbd()
        sleep_ms(ESC_TO_A_WAIT_MS)

        # Press gamepad A
        if not keyboard_only:
            hid.send_pad(buttons=SWITCH_USB_MASK_A)
            sleep_ms(A_PRESS_MS)
            hid.release_pad()
            sleep_ms(POST_A_WAIT_MS)

        # Type the line character by character
        prev_keycode = None
        for ch in line:
            entry = ASCII_TO_KEY.get(ch)
            if entry is None:
                continue
            shift, keycode = entry
            # Must release between repeated keys
            if keycode == prev_keycode:
                hid.release_kbd()
                sleep_ms(KEY_GAP_MS)
            modifier = MOD_LSHIFT if shift else MOD_NONE
            hid.send_kbd(modifier, keycode)
            sleep_ms(KEY_HOLD_MS)
            prev_keycode = keycode

        hid.release_kbd()

        # Press Enter twice
        sleep_ms(KEY_GAP_MS)
        hid.send_kbd(0, HID_KEY_ENTER)
        sleep_ms(ENTER_HOLD_MS)
        hid.release_kbd()
        sleep_ms(ENTER_GAP_MS)

        hid.send_kbd(0, HID_KEY_ENTER)
        sleep_ms(ENTER_HOLD_MS)
        hid.release_kbd()

        # Between batches: wait, press A, wait
        if batch_idx < len(lines) - 1:
            sleep_ms(PRE_A_WAIT_MS)
            if not keyboard_only:
                hid.send_pad(buttons=SWITCH_USB_MASK_A)
                sleep_ms(A_PRESS_MS)
                hid.release_pad()
            sleep_ms(POST_A_WAIT_MS)

    hid.release_all()
    print("Done!")


