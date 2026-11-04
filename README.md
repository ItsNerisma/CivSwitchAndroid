# CivSwitch - No Pico but Androido

> [!IMPORTANT]
> **[CivSwitch](https://github.com/Gezine/CivSwitch) is an exploit by [Gezine](https://github.com/Gezine) :heart:.** This is just a fork allowing you to replace the Pico with a rooted Android phone, acting as a keyboard AND a pro controller. It has been made in a couple of hours, it's pretty rough.

Very odd footage of the thing in action: https://github.com/user-attachments/assets/123a8bc9-2460-47cd-8f14-cf64a20445d4


## What you need

- A docked Switch 2 and the **physical Switch 1 edition of Civilization VII, version 1.0.0**. Check the [upstream project](https://github.com/Gezine/CivSwitch#readme) for console firmware compatibility. I only tested on Switch 2 **23.0.1**.
- A rooted Android phone with [Termux](https://github.com/termux/termux-app/releases). Compatibility with other phones depends on their USB support.
- A USB data cable to connect the phone to the Switch dock.
- Either a PC with **[ADB](https://developer.android.com/tools/releases/platform-tools)**, **[Node.js](https://nodejs.org/en/download)** and npm, or Node.js, npm and Git installed in Termux to build and deploy directly from the phone. The persistent installer also needs Python 3; it can run from the PC or from Termux.

The full procedure, including the persistent installer, has been tested on a **Xiaomi Redmi 10 (`eos`)**, running **Android 11 / MIUI 12.5.26.0.RKUEUXM**, rooted with **[Magisk 31.1](https://github.com/topjohnwu/Magisk/releases/tag/v31.1)**.

## One-time setup

### 1. Prepare the phone

On the phone, download Termux from the **[official GitHub releases page](https://github.com/termux/termux-app/releases)**. Open a release's **Assets** and download the APK ending in **`_universal.apk`**, then install it and open Termux.

Install the tools in the normal Termux shell, before running `su`:

```sh
pkg install git nodejs npm python
```

If you already entered a root shell, run `exit` first: Termux's package manager must run without root.

Grant root access to **Termux** in your root manager (in Magisk, use the **Superuser** tab). Enable **USB debugging** and grant root access to **Shell (ADB)** only if you plan to deploy from a PC.

### 2. Build and deploy

Choose one of these deployment methods. Both build the payload from the current source before installing the scripts.

#### From the phone with Termux

In Termux, use the normal (non-root) shell to clone the repository:

```sh
cd ~
git clone https://github.com/ItsNerisma/CivSwitchNoPico.git
cd CivSwitchNoPico
```

Install the Termux `sudo` wrapper and run the on-device deployment script:

```sh
bash patchsudo.sh
sudo bash deployandr.sh
```

`deployandr.sh` builds `PicoSwitch/payload.txt`, copies the runtime files to `/data/local/tmp/civswitch`, and creates the Termux shortcuts. Run these commands again after pulling project updates to rebuild and redeploy.

You can also do those steps manually without installing the `sudo` wrapper. From the repository root, build the payload in the normal Termux shell:

```sh
cd PicoSwitch && npm install --silent && node compress.js
cd ..
```

Then stage the scripts and generated payload where `test.sh` and `run.sh` expect them, and create the same shortcuts as the deployment script:

```sh
su
setenforce 0
mkdir -p /data/local/tmp/civswitch
cp AndroidSwitch/*.sh AndroidSwitch/*.py /data/local/tmp/civswitch/
cp PicoSwitch/payload.txt /data/local/tmp/civswitch/payload.txt
ln -sf /data/local/tmp/civswitch/test.sh /data/data/com.termux/files/home/test.sh
ln -sf /data/local/tmp/civswitch/run.sh /data/data/com.termux/files/home/run.sh
ln -sf /data/local/tmp/civswitch/teardown.sh /data/data/com.termux/files/home/teardown.sh
```

You can now continue with the test and run steps below. The deployment script automates this build, copy and shortcut setup.

#### From a PC with ADB

Connect the phone, accept the USB debugging authorization, then open a terminal in this repository's root folder on the PC and run the command for your shell:

```sh
# Bash (Linux, macOS, or WSL)
bash deploy.sh

# PowerShell (Windows)
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

This generates the payload, copies everything to the phone and creates shortcuts in Termux. Run it again whenever you update the project.

After either method finishes, continue in Termux on the phone. The deployment step is needed because the `test.sh` and `run.sh` shortcuts use the installed files in `/data/local/tmp/civswitch`; they are not standalone when run directly from the Git checkout.

## Use it on the Switch

### 1. Open the chat

On the Switch:

1. Set the console's **system language** to **English (US)**.
2. Set the **USB keyboard layout** to **English (US)** as well. Both settings are part of the [original Gezine instructions](https://github.com/Gezine/CivSwitch#workflow).
3. Set up [90DNS](https://gitlab.com/a/90dns) before connecting to the internet.
4. Launch Civilization VII and open **MULTIPLAYER → WIRELESS → CREATE GAME → HOST LOBBY → CHAT**. Select the chat input field (click the right stick). DO NOT OPEN THE KEYBOARD, just focus the chat view with the right stick by clicking.

### 2. Check the connection

Keep the phone unplugged. In Termux, run:

```sh
su
setenforce 0 # Temporarily relax SELinux restrictions to allow USB controller emulation
sh test.sh
```

**When prompted**, connect the phone to a USB-A port on the Switch dock.
It should write two test messages in Civ's chat. Wait for the command to finish. At the end it will disconnect the emulated controller from the Switch, it's normal.

### 3. Run the full procedure

Once you're good with the test, reconnect your Joy-Con controllers when prompted and return to the chat input field. **Unplug the phone**, then type in the **same root Termux session**:

```sh
sh run.sh
```

The controller should reconnect and start typing the payload. Leave the game and phone running until the command finishes. The default payload types **87 lines** and takes roughly **15 minutes** :slightly_smiling_face:.

> [!IMPORTANT]
> **You will be asked to reconnect your Joy-Con controllers when the Switch asks at the end.** Confirm the controller prompt so the game can resume and the exploit can finish.

Now, just wait until the console displays **`Awaiting payload at <console-ip>:9026`**. The **Remote JS Loader** is then ready. Run the persistent installer from the repository's root folder on a PC on the same local network, or from the cloned repository in Termux on the phone:

```sh
npm --prefix installer-creator install
python3 installer-creator/install.py <console-ip> # without the port
```

Replace `<console-ip>` with the address shown on the Switch, without `:9026`. The `npm` command installs the installer's dependencies and only needs to be run once per clone.

This will install the persistent loader in the save files of the game. **It replaces the game's single-player saves.** Keep the game open until the installer prints **`INSTALL DONE`**. You can then directly run the exploit without all this bullshit by restarting the game and selecting **Load Game**. HF ! :heart: :tada:

## Credits

- Original [CivSwitch](https://github.com/Gezine/CivSwitch) by [Gezine](https://github.com/Gezine).
