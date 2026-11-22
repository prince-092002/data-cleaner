// Runs the Python cleaning engine in the visitor's browser (Pyodide). Requests: {id, op, args};
// answers: {id, ok, result | error} and, while a job runs, {id, progress: [pct, step]}.
// Needs /py/bundle.json ({"engine/x.py": text, "browser/adapter.py": text, "shims/...": text}).

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/'

export type WorkerOp = 'upload' | 'profile' | 'clean' | 'results' | 'build_xlsx' | 'file' | 'warm'
export interface WorkerRequest {
  id: number
  op: WorkerOp
  args: Record<string, unknown>
}
export type WorkerReply =
  | { id: number; ok: true; result: unknown; bytes?: Uint8Array }
  | { id: number; ok: false; error: { status: number; code: string; message: string } }
  | { id: number; progress: [number, string] }

export interface Py {
  FS: {
    mkdirTree(p: string): void
    writeFile(p: string, data: string | Uint8Array): void
    readFile(p: string): Uint8Array
  }
  loadPackage(names: string[]): Promise<void>
  pyimport(name: string): { install(pkgs: string[]): Promise<void> }
  runPython(code: string): unknown
  globals: { set(name: string, value: unknown): void; get(name: string): (...a: unknown[]) => string }
}

const scope = self as unknown as {
  postMessage(msg: WorkerReply, transfer?: Transferable[]): void
  onmessage: ((e: MessageEvent<WorkerRequest>) => void) | null
}

// Python side: one entry point that never raises, so the JS side only parses a JSON string.
const GLUE = `
import json
from browser import adapter

def call(op, args_json, progress):
    a = json.loads(args_json)
    try:
        if op == "upload":
            r = adapter.upload(a["name"], open("/tmp/in.bin", "rb").read())
        elif op == "profile":
            r = adapter.profile(a["dataset_id"], a.get("sheet"), a.get("header_row"), progress)
        elif op == "clean":
            adapter.clean(a["dataset_id"], json.dumps(a["decisions"]), progress)
            r = {}
        elif op == "results":
            r = adapter.results(a["dataset_id"], a.get("query"))
        elif op == "build_xlsx":
            adapter.build_xlsx(a["dataset_id"])
            r = {"ready": True}
        else:
            data, filename, mime = adapter.file(a["dataset_id"], a["name"])
            open("/tmp/out.bin", "wb").write(data)
            r = {"filename": filename, "mime": mime}
        return json.dumps({"ok": True, "result": r})
    except adapter.AdapterError as e:
        return json.dumps({"ok": False, "error": {"status": e.status, "code": e.code, "message": e.message}})
    except Exception:
        return json.dumps({"ok": False, "error": {"status": 500, "code": "internal_error",
                           "message": "Something went wrong while processing the file."}})
`

let py: Py | null = null

async function boot(): Promise<Py> {
  // shortcut: engine files and packages are fetched on every visit (the browser HTTP cache helps), revisit if cold start hurts
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  const p: Py = await loadPyodide({ indexURL: PYODIDE_URL })
  await p.loadPackage(['polars', 'pydantic', 'pyyaml', 'charset-normalizer', 'micropip'])
  await p.pyimport('micropip').install(['openpyxl', 'ftfy'])
  const bundle: Record<string, string> = await (await fetch('/py/bundle.json')).json()
  for (const [path, text] of Object.entries(bundle)) {
    const full = `/repo/${path}`
    p.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')))
    p.FS.writeFile(full, text)
  }
  p.FS.mkdirTree('/tmp')
  p.runPython("import sys; sys.path[:0] = ['/repo/shims', '/repo']")
  p.runPython(GLUE)
  return p
}

let ready: Promise<Py> | null = null

/** Calls the Python glue. Upload bytes go through the file system, never through the JSON. */
export function callPython(p: Py, op: WorkerOp, args: Record<string, unknown>, progress: (pct: number, step: string) => void) {
  const { data, ...rest } = args
  if (op === 'upload') p.FS.writeFile('/tmp/in.bin', data as Uint8Array)
  return JSON.parse(p.globals.get('call')(op, JSON.stringify(rest), progress))
}

scope.onmessage = async (e) => {
  const { id, op, args } = e.data
  try {
    if (!py) {
      scope.postMessage({ id, progress: [0, 'Loading the cleaning engine'] })
      py = await (ready ??= boot())
    }
    if (op === 'warm') return scope.postMessage({ id, ok: true, result: {} }) // only boots the engine
    const progress = (pct: number, step: string) => scope.postMessage({ id, progress: [pct, step] })
    const reply = callPython(py, op, args, progress)
    if (!reply.ok) return scope.postMessage({ id, ...reply })
    const bytes = op === 'file' ? py.FS.readFile('/tmp/out.bin') : undefined
    scope.postMessage({ id, ...reply, bytes }, bytes ? [bytes.buffer] : [])
  } catch (err) {
    // Loading failed (offline, CDN blocked): later requests try again.
    ready = null
    scope.postMessage({
      id,
      ok: false,
      error: { status: 0, code: 'network_error', message: `The cleaning engine could not start: ${String(err)}` },
    })
  }
}
