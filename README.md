# CivSwitch — Android Edition

> [!IMPORTANT]
> **[CivSwitch](https://github.com/Gezine/CivSwitch) is an exploit by [Gezine](https://github.com/Gezine).** This is just a fork allowing you to replace the Pico with a rooted Android phone, acting as a keyboard AND a pro controller. It has been made in a couple of hours, it's pretty rough.

[▶ It looks like this](assets/rooted-android-civswitch.mp4)

## What you need

- A docked Switch 2 and the **physical Switch 1 edition of Civilization VII, version 1.0.0**. Check the [upstream project](https://github.com/Gezine/CivSwitch#readme) for console firmware compatibility. I only tested on Switch 2 **23.0.1**.
- A rooted Android phone with [Termux](https://github.com/termux/termux-app/releases). Compatibility with other phones depends on their USB support.
- A USB data cable to connect the phone to the PC and the Switch dock.
- A PC with **[ADB](https://developer.android.com/tools/releases/platform-tools)**, **[Node.js](https://nodejs.org/en/download)**, **npm** and a **Bash terminal**. The persistent installer below also needs **[Python 3](https://www.python.org/downloads/)**. On Windows, you can use WSL with USB access configured: see [Microsoft's USB setup guide](https://learn.microsoft.com/en-us/windows/wsl/connect-usb).

The full procedure, including the persistent installer, has been tested on a **Xiaomi Redmi 10 (`eos`)**, running **Android 11 / MIUI 12.5.26.0.RKUEUXM**, rooted with **[Magisk 31.1](https://github.com/topjohnwu/Magisk/releases/tag/v31.1)**.

## One-time setup

### 1. Prepare the phone

On the phone, download Termux from the **[official GitHub releases page](https://github.com/termux/termux-app/releases)**. Open a release's **Assets** and download the APK ending in **`_universal.apk`**, then install it and open Termux.

Install Python **before running `su`**, in the normal Termux shell:

```sh
pkg install python
```

If you already entered a root shell, run `exit` first: Termux's package manager must run without root.

Enable **USB debugging** in Android's Developer options. Connect the phone to the PC and accept the USB debugging authorization on the phone. Grant root access to **Termux** and **Shell (ADB)** in your root manager (in Magisk, use the **Superuser** tab).

### 2. Deploy

Once the phone is connected, open a Bash terminal in this repository's root folder on the PC and run:

```bash
bash deploy.sh
```

This generates the payload, copies everything to the phone and creates shortcuts in Termux. Run it again whenever you update the project.
Once deployment finishes, unplug the phone from the PC. **The remaining steps run from Termux directly on the phone.**

## Use it on the Switch

### 1. Open the chat

On the Switch:

1. Set the console's **system language** to **English (US)**.
2. Set the **USB keyboard layout** to **English (US)** as well. Both settings are part of the [original Gezine instructions](https://github.com/Gezine/CivSwitch#workflow).
3. Set up [90DNS](https://gitlab.com/a/90dns) before connecting to the internet.
4. Launch Civilization VII and open **MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY → CHAT**. Select the chat input field (click the right stick).

### 2. Check the connection

Keep the phone unplugged. In Termux, run:

```sh
su
setenforce 0
sh test.sh
```

**When prompted**, connect the phone to a USB-A port on the Switch dock.
It should write two test messages in Civ's chat. Wait for the command to finish. At the end it will disconnect the emulated controller from the Switch, it's normal.

### 3. Run the full procedure

Once you're good with the test, reconnect your Joy-Con controllers when prompted and return to the chat input field. **Unplug the phone**, then type in the **same root Termux session**:

```sh
sh run.sh
```

The controller should reconnect and start typing the payload. Leave the game and phone running until the command finishes. The default payload types **87 lines** and takes roughly **15 minutes** :3.

> [!IMPORTANT]
> **You will be asked to reconnect your Joy-Con controllers when the Switch asks at the end.** Confirm the controller prompt so the game can resume and the exploit can finish.

Now, just wait until the console displays **`Awaiting payload at <console-ip>:9026`**. The **Remote JS Loader** is then ready. That means you can now run these commands from the repository's root folder on **your PC on the same local network**:

```sh
npm --prefix installer-creator install
python3 installer-creator/install.py <console-ip> # without the port
```

Replace `<console-ip>` with the address shown on the Switch, without `:9026`. The `npm` command installs the installer's dependencies and only needs to be run once.

This will install the persistent loader in the save files of the game. **It replaces the game's single-player saves.** Keep the game open until the installer prints **`INSTALL DONE`**. You can then directly run the exploit without all this bullshit by restarting the game and selecting **Load Game**. HF ! <3

## Credits

- Original [CivSwitch](https://github.com/Gezine/CivSwitch) by [Gezine](https://github.com/Gezine).
- JS exploit core based on [Netflix-N-Hack](https://github.com/NetflixNHack/Netflix-N-Hack) and the [ufm42 fork](https://github.com/ufm42/Netflix-N-Hack).
- PicoSwitch firmware based on [Pico-Switch-Controller](https://github.com/Element2424/Pico-Switch-Controller) by [Element2424](https://github.com/Element2424).
