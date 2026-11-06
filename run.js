#!/usr/bin/env node
// Prepare the payload here; Python handles the phone's USB connection.
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

async function main(args = process.argv.slice(2)) {
  const [mode = "run", ...commandArgs] = args;

  if (mode === "--help" || commandArgs.includes("--help") || commandArgs.includes("-h")) {
    help();
    return;
  }

  if (["run", "test", "persist"].includes(mode) &&
      !fs.existsSync(path.join(__dirname, "node_modules/terser/package.json"))) {
    throw new Error("Run npm install in this project folder first.");
  }

  if (mode === "persist") {
    if (!commandArgs.length) {
      throw new Error("Usage: npm run persist -- <console-ip> [port] [payload.js]");
    }

    await runCommand(process.platform === "win32" ? "python" : "python3", [
      path.join(__dirname, "installer-creator/install.py"), ...commandArgs,
    ]);
    return;
  }

  if (!["run", "test", "teardown"].includes(mode)) {
    throw new Error(`Unknown command: ${mode}`);
  }

  if (!isTermux()) {
    throw new Error("USB commands require a rooted Android phone with Termux. Use npm run start -- --help for usage.");
  }

  const termuxPython = path.join(path.dirname(process.execPath), "python3");
  if (!fs.existsSync(termuxPython)) {
    throw new Error("Python is missing. In Termux, run: pkg install python");
  }

  const request = {};
  if (mode === "run") {
    console.log("Preparing the payload...");
    request.lines = await require("./compress")(fs.readFileSync(path.join(__dirname, "core.js"), "utf8"));
  }

  await runCommand("bash", [path.join(__dirname, "bash/usb.sh"), termuxPython, mode, ...commandArgs], request);
}

function isTermux() {
  return process.platform === "android" || /\/com\.termux\//.test(process.execPath);
}

function help() {
  console.log(`Usage:
  npm run start                     Send the full payload through Android USB
  npm run test                      Type two test messages in Civ's chat
  npm run teardown                  Restore USB and SELinux after an interruption
  npm run persist -- <ip> [port] [payload.js]

USB options: --start-delay <seconds>, --connect-timeout <seconds>, --usb-trace
Run these commands in the normal Termux shell. Root access is requested automatically.`);
}

// For USB commands, stdin carries the payload and stays open while Python runs.
function runCommand(command, args, request) {
  return new Promise((resolve, reject) => {
    const hasControlPipe = request !== undefined;
    const child = spawn(command, args, {
      cwd: __dirname,
      stdio: [hasControlPipe ? "pipe" : "inherit", "inherit", "inherit"],
    });

    let interrupted = false;
    let inputError;
    const interrupt = () => {
      if (interrupted) {
        return;
      }

      interrupted = true;

      if (hasControlPipe) {
        // Python sees the closed pipe and restores USB before it exits.
        child.stdin.end();
      } else {
        child.kill("SIGTERM");
      }
    };

    const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
    for (const name of signals) {
      process.on(name, interrupt);
    }

    const cleanup = () => {
      for (const name of signals) {
        process.off(name, interrupt);
      }

      if (hasControlPipe) {
        child.stdin.destroy();
      }
    };

    child.once("error", (error) => {
      cleanup();
      reject(error);
    });
    child.once("close", (code, signal) => {
      cleanup();

      if (interrupted && (code === 0 || code === 130)) {
        process.exitCode = 130;
        resolve();
      } else if (code === 0 && !inputError) {
        resolve();
      } else {
        reject(inputError || new Error(`${path.basename(command)} exited with ${signal || `code ${code}`}`));
      }
    });

    if (hasControlPipe) {
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") {
          inputError = error;
        }
      });

      // Python reads this line before changing USB or SELinux. Closing the
      // pipe later tells Python to stop and restore the phone.
      child.stdin.write(JSON.stringify(request) + "\n");
    }
  });
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`ERROR: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { main, runCommand };
