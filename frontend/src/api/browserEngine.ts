// Same functions as client.ts, answered by the Python engine running in a Web Worker in this
// browser tab instead of by the server. Selected by VITE_ENGINE=browser (see client.ts).
import type {
  Decisions, DownloadName, JobStatus, JobType, ProfileRequest, ProfileResponse, ResultsQuery, ResultsResponse, UploadResponse,
} from './types'
import type { WorkerReply, WorkerRequest } from '../worker/engine.worker'
import { ApiError } from './client'

type Pending = { resolve: (r: Extract<WorkerReply, { ok: true }>) => void; reject: (e: ApiError) => void; onProgress?: (pct: number, step: string) => void }

let worker: Worker | null = null
let nextId = 1
const pending = new Map<number, Pending>()
const jobs = new Map<string, JobStatus>()
const datasets = new Set<string>()
const profiles = new Map<string, ProfileResponse>()
const urls = new Map<string, string>() // `${datasetId}/${name}` -> blob: URL
const names = new Map<string, string>() // blob: URL -> download file name

function getWorker(): Worker {
  if (worker) return worker
  worker = new Worker(new URL('../worker/engine.worker.ts', import.meta.url), { type: 'module' })
  worker.onmessage = (e: MessageEvent<WorkerReply>) => {
    const msg = e.data
    const p = pending.get(msg.id)
    if (!p) return
    if ('progress' in msg) return p.onProgress?.(msg.progress[0], msg.progress[1])
    pending.delete(msg.id)
    if (msg.ok) p.resolve(msg)
    else p.reject(new ApiError(msg.error.status, msg.error.code, msg.error.message))
  }
  worker.onerror = () => {
    const failed = [...pending.values()]
    pending.clear()
    worker = null
    for (const p of failed) p.reject(new ApiError(0, 'network_error', 'The cleaning engine stopped unexpectedly. Please try again.'))
  }
  return worker
}

function call(op: WorkerRequest['op'], args: WorkerRequest['args'], onProgress?: Pending['onProgress'], transfer: Transferable[] = []) {
  const id = nextId++
  return new Promise<Extract<WorkerReply, { ok: true }>>((resolve, reject) => {
    pending.set(id, { resolve, reject, onProgress })
    getWorker().postMessage({ id, op, args } satisfies WorkerRequest, transfer)
  })
}

const now = () => new Date().toISOString()

/** Starts `work` in the background and answers at once with the job id. */
function startJob(datasetId: string, type: JobType, work: (progress: (pct: number, step: string) => void) => Promise<void>) {
  const job: JobStatus = {
    job_id: crypto.randomUUID(), dataset_id: datasetId, type, status: 'running', progress_pct: 0,
    current_step: '', error: null, created_at: now(), updated_at: now(),
  }
  jobs.set(job.job_id, job)
  const update = (patch: Partial<JobStatus>) => jobs.set(job.job_id, { ...jobs.get(job.job_id)!, ...patch, updated_at: now() })
  work((pct, step) => update({ progress_pct: pct, current_step: step })).then(
    () => update({ status: 'done', progress_pct: 100 }),
    (e: unknown) => {
      const a = e instanceof ApiError ? e : new ApiError(500, 'internal_error', 'Something went wrong while processing the file.')
      update({ status: 'failed', error: { code: a.code, message: a.message } })
    },
  )
  return { job_id: job.job_id }
}

function forget(datasetId: string) {
  for (const key of [...urls.keys()].filter((k) => k.startsWith(`${datasetId}/`))) {
    URL.revokeObjectURL(urls.get(key)!)
    urls.delete(key)
  }
}

async function fetchFile(datasetId: string, name: DownloadName) {
  const r = await call('file', { dataset_id: datasetId, name })
  const meta = r.result as { filename: string; mime: string }
  const url = URL.createObjectURL(new Blob([r.bytes as BlobPart], { type: meta.mime }))
  urls.set(`${datasetId}/${name}`, url)
  names.set(url, meta.filename)
}

export async function getHealth(): Promise<{ status: string; max_upload_mb: number }> {
  // The upload screen asks on mount: use that moment to boot the engine before a file is picked.
  call('warm', {}).catch(() => {})
  return { status: 'ok', max_upload_mb: 20 }
}

export async function uploadDataset(file: File): Promise<UploadResponse> {
  const data = new Uint8Array(await file.arrayBuffer())
  const r = await call('upload', { name: file.name, data }, undefined, [data.buffer])
  const up = r.result as UploadResponse
  for (const old of datasets) { // the worker keeps one dataset only, so earlier ones are gone
    forget(old)
    profiles.delete(old)
    for (const [id, job] of jobs) if (job.dataset_id === old) jobs.delete(id)
  }
  datasets.clear()
  datasets.add(up.dataset_id)
  return up
}

export async function startProfile(datasetId: string, body: ProfileRequest = {}) {
  // shortcut: a bad dataset id or sheet shows up as a failed job, not as an error from this call, revisit if a screen needs the 4xx here
  forget(datasetId)
  profiles.delete(datasetId)
  return startJob(datasetId, 'profile', async (progress) => {
    const r = await call('profile', { dataset_id: datasetId, ...body }, progress)
    profiles.set(datasetId, r.result as ProfileResponse)
  })
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const job = jobs.get(jobId)
  if (!job) throw new ApiError(404, 'not_found', 'This job was not found. Files are deleted 24 hours after upload.')
  return { ...job }
}

function requireKnown(datasetId: string) {
  // A page reload forgets every dataset: answer at once instead of waiting for the engine to boot.
  if (!datasets.has(datasetId)) {
    throw new ApiError(404, 'not_found', 'This dataset was not found. Files are deleted 24 hours after upload.')
  }
}

export async function getProfile(datasetId: string): Promise<ProfileResponse> {
  // shortcut: the profile is kept only in this page (the worker has no get-profile call), a reload loses it, revisit if reloads must restore
  const profile = profiles.get(datasetId)
  if (profile) return profile
  requireKnown(datasetId)
  throw new ApiError(409, 'not_ready', 'The profile is not ready yet. Start a profile job and wait for it to finish.')
}

export async function startClean(datasetId: string, decisions: Decisions) {
  forget(datasetId)
  return startJob(datasetId, 'clean', async (progress) => {
    await call('clean', { dataset_id: datasetId, decisions }, progress)
    // downloadUrl() is synchronous, so every file but Excel is fetched now.
    for (const name of ['clean.csv', 'report.html', 'recipe.yaml', 'changelog.csv'] as const) await fetchFile(datasetId, name)
  })
}

export async function getResults(datasetId: string, query: ResultsQuery = {}) {
  requireKnown(datasetId)
  const r = await call('results', { dataset_id: datasetId, query })
  return r.result as ResultsResponse
}

export async function prepareExcel(datasetId: string): Promise<{ ready: boolean }> {
  await call('build_xlsx', { dataset_id: datasetId })
  await fetchFile(datasetId, 'clean.xlsx')
  return { ready: true }
}

export function downloadUrl(datasetId: string, name: string): string {
  return urls.get(`${datasetId}/${name}`) ?? '#'
}

/** The file name a download should have; the screens' links only know the blob: URL. */
export function downloadName(url: string): string {
  return names.get(url) ?? ''
}
