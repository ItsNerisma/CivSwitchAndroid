# CivSwitch - No Pico but Androido

> [!IMPORTANT]
> **[CivSwitch](https://github.com/Gezine/CivSwitch) is an exploit by [Gezine](https://github.com/Gezine) :heart:.** This is just a fork allowing you to replace the Pico with a rooted Android phone, acting as a keyboard AND a pro controller. It has been made in a couple of hours, it's pretty rough.

Very odd footage of the thing in action: https://github.com/user-attachments/assets/123a8bc9-2460-47cd-8f14-cf64a20445d4

## What you need

- A docked Switch 2 and the **physical Switch 1 edition of Civilization VII, version 1.0.0**. Check the [upstream project](https://github.com/Gezine/CivSwitch#readme) for console firmware compatibility. I only tested on Switch 2 **23.0.1**.
- A rooted Android phone with [Termux](https://github.com/termux/termux-app/releases), **Node.js 18+**, npm and Python 3. Compatibility with other phones depends on their USB support (ConfigFS and FunctionFS).
- A USB data cable to connect the phone to the Switch dock.

The procedure, including the persistent installer, was tested on a **Xiaomi Redmi 10 (`eos`)**, running **Android 11 / MIUI 12.5.26.0.RKUEUXM**, rooted with **[Magisk 31.1](https://github.com/topjohnwu/Magisk/releases/tag/v31.1)**.

## One-time setup

### 1. Prepare the phone

On the phone, download Termux from the **[official GitHub releases page](https://github.com/termux/termux-app/releases)**. Open a release's **Assets** and download the APK ending in **`_universal.apk`**, then install it and open Termux.

Install the tools in a fresh Termux shell:

```sh
pkg update
pkg install git nodejs npm python
```

If you already entered a root shell, run `exit` first: Termux's package manager must run without root. 

>[!NOTE] 
> Even tho you must not be root to install the pkgs, you'll **need Termux to be granted root access** by your root helper for later commands (in Magisk, use the **Superuser** tab, find Termux and tick its checkbox).

### 2. Get the project

Choose whichever method you prefer. Keep the working folder in Termux's home directory, where Git and npm can work normally.

#### Clone directly on the phone

```sh
cd ~ # on a fresh termux shell you should already be there
git clone https://github.com/ItsNerisma/CivSwitchAndroid.git
cd CivSwitchAndroid
```

### 3. Install once

From the project folder, still in the normal Termux shell **without `sudo`**:

```sh
npm install
```

Node.js, npm and Python are needed **on the phone**, even if you transferred the project from a PC.

## Use it on the Switch

### 1. Open the chat

On the Switch:

1. Set the console's **system language** to **English (US)**.
2. Set the **USB keyboard layout** to **English (US)** as well. Both settings are part of the [original Gezine instructions](https://github.com/Gezine/CivSwitch#workflow).
3. Set up [90DNS](https://gitlab.com/a/90dns) before connecting to the internet.
4. Launch Civilization VII and open **MULTIPLAYER → WIRELESS → CREATE GAME (R stick press) → HOST LOBBY (+ button press) → CHAT (R stick press)**.

**DO NOT OPEN THE KEYBOARD**, just focus the chat view with the right stick by clicking.

### 2. Test the thing

Keep the phone unplugged. From the project folder in a non root Termux shell, run:

```sh
npm run test 
```

The script saves the initial SELinux state, runs `setenforce 0` if needed, and prepares the USB controller.

**When prompted**, connect the phone to a USB-A port on the Switch dock.
It should write two test messages in Civ's chat. Wait for the command to finish. At the end it will disconnect the emulated controller from the Switch, it's normal. Android USB and the initial SELinux state are restored automatically.

### 3. Run the exploit

Once you're good with the test, reconnect your Joy-Con controllers when prompted then run:

```sh
npm run start
```

The script compresses the current `core.js` in memory, then asks you to connect the phone. The controller should reconnect and start typing the payload. Leave the game and phone running until the command finishes. The default payload types **87 lines** and takes roughly **15 minutes** :slightly_smiling_face:.

> [!IMPORTANT]
> **You will be asked to reconnect your Joy-Con controllers when the Switch asks at the end.** Confirm the controller prompt so the game can resume and the exploit can finish.

Now, just wait until the console displays **`Awaiting payload at <console-ip>:9026`**. The **Remote JS Loader** is now ready :tada:

### 4. Persist the exploit (optional)

You can do this **directly from the phone**, no PC needed :D Connect the phone to the same local network as the Switch, then from the project folder in Termux:

```sh
npm run persist -- <console-ip> # without the port
```

This will install the persistent loader in the save files of the game. **It replaces the game's single-player saves.** Keep the game open until the installer prints **`INSTALL DONE`**. You can then directly run the exploit without all this bullshit by restarting the game and selecting **Load Game**. HF ! :heart: :tada:

For a custom loader port or JS payload, see [the installer instructions](installer-creator/README.md).

> [!NOTE]
> You can also run this from a PC with Node.js, npm and Python 3 installed: run `npm install` once in the PC's copy of the project, then the same `npm run persist` command. The PC does not need root or ADB. On Windows, Python must be available as `python`.

## Recovery

Both `npm run start` and `npm run test` restore USB and the original SELinux state on completion, errors and `Ctrl+C`. If USB restoration fails, SELinux restoration is still attempted and the backup is kept.

A force-stop or `kill -9` can prevent immediate cleanup. Reopen Termux, go to the project folder and run:

```sh
npm run teardown
```

The next test or run also attempts recovery before starting a new session. After a phone reboot, stale state from the previous boot is discarded instead of replayed.

Recovery data and the shared session lock live in `/data/local/tmp/civswitch-state`, independently of the project folder. This is created automatically, you don't need to copy anything there. If recovery fails, keep these files and read the printed error before trying again.

## Useful commands

```sh
npm run start -- --connect-timeout 120   # More time to plug the phone in
npm run test -- --usb-trace          # USB diagnostics
npm run start -- --start-delay 5         # Wait a little longer before typing
npm run start -- --help
```

Once the Remote JS Loader is running, send an extra JS payload with:

```sh
python3 send_js.py <console-ip> payloads/helloworld.js
```

## Credits

- Original [CivSwitch](https://github.com/Gezine/CivSwitch) by [Gezine](https://github.com/Gezine).
