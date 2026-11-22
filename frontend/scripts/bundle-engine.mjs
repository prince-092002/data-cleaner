// Packs the Python engine for Pyodide: frontend/public/py/bundle.json = {"engine/x.py": text, "browser/adapter.py": text, "shims/y.py": text}.
// Usage: node scripts/bundle-engine.mjs [repoRoot]   (repoRoot defaults to the parent of frontend/)
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? path.join(import.meta.dirname, "..", ".."));
const out = {};

function walk(dir, prefix) {
  for (const f of fs.readdirSync(dir)) {
    if (f === "__pycache__") continue;
    const p = path.join(dir, f);
    if (fs.statSync(p).isDirectory()) walk(p, prefix + f + "/");
    else if (f.endsWith(".py")) out[prefix + f] = fs.readFileSync(p, "utf8");
  }
}

const adapter = path.join(root, "browser", "adapter.py");
const shims = path.join(root, "browser", "shims");
for (const need of [path.join(root, "engine"), adapter, shims]) {
  if (!fs.existsSync(need)) {
    console.error(`bundle-engine: missing ${path.relative(root, need)} (browser/ is created by the browser-runtime work)`);
    process.exit(1);
  }
}
walk(path.join(root, "engine"), "engine/");
out["browser/adapter.py"] = fs.readFileSync(adapter, "utf8");
walk(shims, "shims/");

const dest = path.join(root, "frontend", "public", "py");
fs.mkdirSync(dest, { recursive: true });
fs.writeFileSync(path.join(dest, "bundle.json"), JSON.stringify(out));
console.log(Object.keys(out).length, "files bundled");
