const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { runCommand } = require("../run");

const root = path.resolve(__dirname, "..");

test("launcher failure is reported without hanging on the open control pipe", async () => {
  await assert.rejects(runCommand(process.execPath, ["-e", "process.exit(7)"], {}), /code 7/);
});

test("USB helper preserves arguments containing spaces, apostrophes and shell syntax", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "civswitch '$(false) "));
  try {
    const python = path.join(dir, "python3");
    fs.writeFileSync(python, `#!/bin/sh\nexec '${process.execPath.replaceAll("'", "'\\''")}' -e 'console.log(JSON.stringify(process.argv.slice(1)))' -- "$@"\n`, { mode: 0o755 });
    fs.writeFileSync(path.join(dir, "su"), '#!/bin/sh\nexec /bin/sh -c "$2"\n', { mode: 0o755 });
    const result = spawnSync("bash", [path.join(root, "bash/usb.sh"), python, "test", "--start-delay", "2"], {
      encoding: "utf8", env: { ...process.env, PATH: `${dir}:${process.env.PATH}` },
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), ["-u", path.join(root, "AndroidSwitch/civswitch.py"), "test", "--start-delay", "2"]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("Ctrl+C closes the control pipe and waits for child cleanup", { timeout: 10000 }, async () => {
  const code = `
    const { runCommand } = require(${JSON.stringify(path.join(root, "run.js"))});
    runCommand(process.execPath, ['-e', \`
      process.on('SIGTERM', () => { console.log('WRONG_SIGNAL'); process.exit(1); });
      process.stdin.once('data', () => console.log('READY'));
      process.stdin.on('end', () => setTimeout(() => { console.log('RESTORED'); process.exit(130); }, 100));
      process.stdin.resume();
    \`], {}).catch(error => { console.error(error); process.exitCode = 1; });
  `;
  const child = spawn(process.execPath, ["-e", code], { stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  let errors = "";
  let interrupted = false;
  const closed = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => resolve(code));
  });
  child.stdout.on("data", (chunk) => {
    output += chunk;
    if (!interrupted && output.includes("READY")) {
      interrupted = true;
      child.kill("SIGINT");
    }
  });
  child.stderr.on("data", (chunk) => { errors += chunk; });
  assert.equal(await closed, 130, errors);
  assert.match(output, /RESTORED/);
  assert.doesNotMatch(output, /WRONG_SIGNAL/);
});

test("npm help works outside the project folder without Android or root", () => {
  const result = spawnSync(process.execPath, [path.join(root, "run.js"), "run", "--help"], {
    cwd: os.tmpdir(), encoding: "utf8",
  });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /npm run test/);
});
