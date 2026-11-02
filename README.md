# CivSwitch — Android Edition

> [!IMPORTANT]
> **[CivSwitch](https://github.com/Gezine/CivSwitch) is an exploit by [Gezine](https://github.com/Gezine).** This repository adapts the input procedure to rooted Android phones.

Use a rooted Android phone to type the CivSwitch payload into Civilization VII on your Switch. The phone acts as a controller and keyboard; no Raspberry Pi Pico is needed.

## What you need

- A docked Switch or Switch 2 and the **physical Switch 1 edition of Civilization VII, version 1.0.0**. Check the [upstream project](https://github.com/Gezine/CivSwitch#readme) for console firmware compatibility.
- A rooted Android phone with [Termux](https://github.com/termux/termux-app/releases). Compatibility with other phones depends on their USB support.
- A USB data cable to connect the phone to the PC and the Switch dock.
- A PC with **ADB**, **Node.js**, **npm** and a **Bash terminal**. The optional PC tools below also need **Python 3**. On Windows, you can use WSL with USB access configured.

The full procedure, including the persistent installer, has been confirmed on a **Xiaomi Redmi 10 (`eos`)**, running **Android 11 / MIUI 12.5.26.0.RKUEUXM**, rooted with **[Magisk 31.1](https://github.com/topjohnwu/Magisk/releases/tag/v31.1)**.

## One-time setup

### 1. Prepare the phone

Install and open Termux, then run this command **in Termux, before entering `su`**:

```sh
pkg install python
```

Enable **USB debugging** in Android's Developer options. Connect the phone to the PC and accept the USB debugging authorization. Grant root access when prompted during deployment and when using `su` in Termux.

### 2. Deploy

From this repository on the PC:

```bash
bash deploy.sh
```

This generates the payload, copies everything to the phone and creates shortcuts in Termux. Run it again whenever you update the project. You do not need to build or flash Pico firmware.

Once deployment finishes, unplug the phone from the PC. The remaining steps run from Termux.

## Use it on the Switch

### 1. Open the chat

On the Switch:

1. Set the console's **system language** to **English (US)**.
2. Set the **USB keyboard layout** to **English (US)** as well. Both settings are part of the [original Gezine instructions](https://github.com/Gezine/CivSwitch#workflow).
3. Set up [90DNS](https://gitlab.com/a/90dns) before connecting to the internet.
4. Launch Civilization VII and open **MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY → CHAT**. Select the chat input field.

### 2. Check the connection

Keep the phone unplugged. In Termux, run:

```sh
su
setenforce 0
sh ~/test.sh
```

When prompted, connect the phone to a USB-A port on the Switch dock. Two test messages should appear in the chat. Wait for the command to finish before continuing.

Repeat `su` in a new Termux session and `setenforce 0` after restarting the phone.

### 3. Run the full procedure

Keep your **Joy-Con controllers ready** for the end of the procedure. Return to the chat input field, unplug the phone, and run **in the same root Termux session**:

```sh
sh ~/run.sh
```

Connect the phone to the dock when prompted, then leave the game and phone running until the command finishes. The default payload types **87 lines** and takes roughly **15 minutes**; the line count can change with payload updates.

> [!IMPORTANT]
> **Reconnect your Joy-Con controllers as soon as all lines have been sent and `run.sh` finishes** (`87/87` with the current default payload). The phone stops acting as a controller at this point, so the Switch can display a controller reconnection prompt. Reconnect the Joy-Con controllers and confirm the prompt so the game can resume and the exploit can finish.

Keep the game open and wait until the console displays **`Awaiting payload at <console-ip>:9026`**. The **Remote JS Loader** is then ready. Use that IP address, without `:9026`, in the PC commands below.

Both `test.sh` and `run.sh` prepare the phone automatically and restore its normal USB connection when they finish, on Ctrl+C, or on an error. Run only one command at a time.

## After the loader starts

You can send a JavaScript file from a PC on the same network:

```bash
python3 send_js.py <console-ip> payloads/helloworld.js
```

For an optional persistent trigger, follow the [installer guide](installer-creator/README.md), including its `npm install` step. This requires Python 3 on the PC and replaces the game's single-player save files.

## If something goes wrong

| Problem | What to do |
|---------|------------|
| The PC cannot see the phone | Check USB debugging, authorization and the data cable. With WSL, reattach the phone through USBIP after a USB mode change if necessary. |
| `Python not found` | Open Termux and run `pkg install python` outside the root shell. |
| `Permission denied` or a root error | Run `su`, allow root access, then run `setenforce 0`. |
| No controller or keyboard response | Start with the cable unplugged, run `sh ~/test.sh`, then connect to the dock. Check the chat input field and English (US) keyboard layout. |
| All lines were sent, but the loader has not appeared | Reconnect the Joy-Con controllers and confirm any controller reconnection prompt so the game can resume. Keep the game open and wait for `Awaiting payload at ...:9026`. |
| Normal USB does not return | Stop the active command with Ctrl+C, then run `sh ~/teardown.sh` as root. If necessary, restart the phone. |

For more detail when reporting a problem, repeat the test with:

```sh
sh ~/test.sh --usb-trace
```

`--usb-trace` is optional.

## Credits

- Original [CivSwitch](https://github.com/Gezine/CivSwitch) by [Gezine](https://github.com/Gezine).
- JS exploit core based on [Netflix-N-Hack](https://github.com/NetflixNHack/Netflix-N-Hack) and the [ufm42 fork](https://github.com/ufm42/Netflix-N-Hack).
- PicoSwitch firmware based on [Pico-Switch-Controller](https://github.com/Element2424/Pico-Switch-Controller) by [Element2424](https://github.com/Element2424).
