#!/usr/bin/env node
// npm entry point. Keep compression unprivileged; elevate only the USB helper.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function isTermux() {
  return process.platform === "android" || /\/com\.termux\//.test(process.execPath);
}

function runCommand(command, args, request) {
  return new Promise((resolve, reject) => {
    const controlled = request !== undefined;
    const child = spawn(command, args, {
      cwd: __dirname,
      stdio: [controlled ? "pipe" : "inherit", "inherit", "inherit"],
    });
    let interrupted = false;
    let inputError;
    const interrupt = () => {
      if (interrupted) return;
      interrupted = true;
      if (controlled) {
        // EOF reaches the root Python process through su. Killing su itself
        // could orphan Python, and Termux cannot directly signal a root PID.
        child.stdin.end();
      } else {
        child.kill("SIGTERM");
      }
    };
    const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
    for (const name of signals) process.on(name, interrupt);
    const cleanup = () => {
      for (const name of signals) process.off(name, interrupt);
      if (controlled) child.stdin.destroy();
    };
    child.once("error", (error) => { cleanup(); reject(error); });
    child.once("close", (code, signal) => {
      cleanup();
      if (interrupted && (code === 0 || code === 130)) {
        process.exitCode = 130;
        resolve();
      } else if (code === 0 && !inputError) resolve();
      else reject(inputError || new Error(`${path.basename(command)} exited with ${signal || `code ${code}`}`));
    });
    if (controlled) {
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") inputError = error;
      });
      // One JSON line is the request; the open pipe is the lifetime of the
      // launcher. Python reads the whole payload before touching USB or SELinux.
      child.stdin.write(JSON.stringify(request) + "\n");
    }
  });
}

function help() {
  console.log(`Usage:
  npm start                         Send the full payload through Android USB
  npm run test                      Type two test messages in Civ's chat
  npm run teardown                  Restore USB and SELinux after an interruption
  npm run persist -- <ip> [port] [payload.js]

USB options: --start-delay <seconds>, --connect-timeout <seconds>, --usb-trace
Run these commands in the normal Termux shell. Root access is requested automatically.`);
}

async function main(args = process.argv.slice(2)) {
  const [mode = "run", ...rest] = args;
  if (mode === "--help" || rest.includes("--help") || rest.includes("-h")) {
    help();
    return;
  }
  if (mode === "setup") {
    if (isTermux()) await runCommand("bash", [path.join(__dirname, "bash/setup.sh")]);
    else console.log("[setup] Dependencies ready. USB commands run on rooted Android with Termux.");
    return;
  }
  if (mode === "persist") {
    if (!rest.length) throw new Error("Usage: npm run persist -- <console-ip> [port] [payload.js]");
    await runCommand(process.platform === "win32" ? "python" : "python3", [
      path.join(__dirname, "installer-creator/install.py"), ...rest,
    ]);
    return;
  }
  if (!["run", "test", "teardown"].includes(mode)) throw new Error(`Unknown command: ${mode}`);
  if (!isTermux()) throw new Error("USB commands require a rooted Android phone with Termux. Use npm start -- --help for usage.");
  const python = path.join(path.dirname(process.execPath), "python3");
  if (!fs.existsSync(python)) throw new Error("Python is missing. In Termux, run: pkg install python");
  const request = {};
  if (mode === "run") {
    console.log("Preparing the payload...");
    request.lines = await require("./compress")(fs.readFileSync(path.join(__dirname, "core.js"), "utf8"));
  }
  await runCommand("bash", [path.join(__dirname, "bash/usb.sh"), python, mode, ...rest], request);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { main, runCommand };
