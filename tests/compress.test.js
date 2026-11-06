const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { minify } = require("terser");
const compress = require("../compress");

test("in-memory chat lines decode to the complete minified source, even out of order", async () => {
  const source = fs.readFileSync(path.join(__dirname, "../core.js"), "utf8");
  const lines = await compress(source);
  assert.ok(lines.length > 1);
  for (const line of lines) {
    assert.ok(Buffer.byteLength(line + "\n", "ascii") <= 254);
    assert.match(line, /^[\x20-\x7e]+$/);
  }
  let tick;
  let decoded;
  let evaluations = 0;
  const context = vm.createContext({
    document: { body: {} },
    setInterval: (fn) => { tick = fn; return 1; },
    clearInterval() {},
  });
  context.window = context;
  context.eval = (code) => {
    if (evaluations++ === 0) vm.runInContext(code, context, { timeout: 1000 });
    else decoded = code; // Capture the exploit; never execute it in a test.
  };
  const handlers = lines.map((line) => line.match(/onerror="(.*)"><div class="$/)[1]);
  const runHandler = (handler) => vm.runInContext(`(function(){${handler}})()`, context);
  for (const handler of handlers.slice(0, -1).reverse()) runHandler(handler);
  assert.equal(decoded, undefined);
  runHandler(handlers.at(-1));
  tick();
  const expected = await minify(source, { compress: true, mangle: true, module: true });
  assert.equal(decoded, expected.code);
});

test("invalid JavaScript fails before there are any lines to send", async () => {
  await assert.rejects(compress("function {"));
});
