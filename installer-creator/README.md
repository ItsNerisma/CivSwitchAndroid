# installer-creator

One script installs the boot-persistent CIV7 savefile-XSS trigger on a console, using the bundled template (the console needs NO existing save). It runs directly in Termux on the phone, or from a PC.

## Usage

The console must be running the Remote JS Loader (Android USB bootstrap or a previously installed trigger). Connect the phone or PC to the same local network as the console.

```
# From the repository root (PC or Termux)
npm install
npm run persist -- <console-ip> [port] [payload.js]
```

- `<console-ip>`  required
- `[port]`        optional, default 9026 (the Remote JS Loader port)
- `[payload.js]`  optional, defaults to `core.js` at the repository root - the shipped default is the Remote JS Loader: after reboot, Load Game brings the loader up at boot.

Everything else is automatic: the payload is wrapped and compressed (terser -> deflate -> inflate-stage, with an offline round-trip check), the save template is uploaded to the loader in chunked connections (~4, a few seconds), then an apply payload locates the `currentTurnDate` record in the template by field hash, splices the compressed stage into it, wipes every file in `save:/saves/Single/`, writes `save:/saves/Single/XSTRIG.Civ7Save`, and commits.
Exit code 0 only on `INSTALL DONE`.

After install: reboot the game, main menu -> **Load Game** -> the list builds -> the stager fires -> hex decode -> eval(stage) -> inflate -> your payload runs, every boot.

## Files

- `install.py`        the one tool (compress + upload + apply)
- `save_template.bin` pristine save clone base
- `compress_stage.js` node compression helper (decoder inlined from the root compress.js; verifies the stage inflates EXACT)
