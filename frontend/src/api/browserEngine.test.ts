import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { WorkerReply, WorkerRequest } from '../worker/engine.worker'

type Handler = (req: WorkerRequest, emit: (r: WorkerReply) => void) => void
let handler: Handler
let requests: WorkerRequest[]

class FakeWorker {
  onmessage: ((e: { data: WorkerReply }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  postMessage(req: WorkerRequest) {
    requests.push(req)
    queueMicrotask(() => handler(req, (r) => this.onmessage?.({ data: r })))
  }
}

const err = (status: number, code: string, message: string) => ({ ok: false as const, error: { status, code, message } })
const flush = () => new Promise((r) => setTimeout(r, 0))

async function load() {
  vi.resetModules() // a fresh worker and fresh job tables per test
  return await import('./browserEngine')
}

beforeEach(() => {
  requests = []
  handler = (req, emit) => emit({ id: req.id, ok: true, result: {} })
  vi.stubGlobal('Worker', FakeWorker)
  let n = 0
  URL.createObjectURL = vi.fn(() => `blob:fake-${++n}`)
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.unstubAllGlobals())

const upload = { dataset_id: 'd1', filename: 'a.csv', file_type: 'csv', size_bytes: 3, expires_at: 'x', sheets: [] }
const profile = { dataset_id: 'd1', proposals: [] }

describe('browser engine', () => {
  it('reports the 20 MB limit', async () => {
    const e = await load()
    await expect(e.getHealth()).resolves.toEqual({ status: 'ok', max_upload_mb: 20 })
  })

  it('starts booting the worker when the app asks for health', async () => {
    const e = await load()
    await e.getHealth()
    expect(requests.map((r) => r.op)).toEqual(['warm'])
  })

  it('answers 404 at once, without the worker, for a dataset this page never saw', async () => {
    const e = await load()
    await expect(e.getResults('old-id')).rejects.toMatchObject({ status: 404, code: 'not_found' })
    await expect(e.getProfile('old-id')).rejects.toMatchObject({ status: 404, code: 'not_found' })
    expect(requests).toEqual([])
  })

  it('uploads the file bytes to the worker', async () => {
    handler = (req, emit) => emit({ id: req.id, ok: true, result: upload })
    const e = await load()
    await expect(e.uploadDataset(new File(['a,b'], 'a.csv'))).resolves.toEqual(upload)
    expect(requests[0].op).toBe('upload')
    expect(requests[0].args.name).toBe('a.csv')
    expect((requests[0].args.data as Uint8Array).length).toBe(3)
  })

  it('runs a profile job: queued at once, progress, then done with the profile', async () => {
    let finish!: () => void
    handler = (req, emit) => {
      if (req.op === 'upload') return emit({ id: req.id, ok: true, result: upload })
      emit({ id: req.id, progress: [40, 'Detecting structure'] })
      finish = () => emit({ id: req.id, ok: true, result: profile })
    }
    const e = await load()
    await e.uploadDataset(new File(['a,b'], 'a.csv'))
    const { job_id } = await e.startProfile('d1', { header_row: 0 })
    expect(requests.at(-1)?.args).toMatchObject({ dataset_id: 'd1', header_row: 0 })
    await flush()
    expect(await e.getJob(job_id)).toMatchObject({
      job_id, dataset_id: 'd1', type: 'profile', status: 'running', progress_pct: 40, current_step: 'Detecting structure', error: null,
    })
    await expect(e.getProfile('d1')).rejects.toMatchObject({ status: 409, code: 'not_ready' })
    finish()
    await flush()
    expect(await e.getJob(job_id)).toMatchObject({ status: 'done', progress_pct: 100 })
    await expect(e.getProfile('d1')).resolves.toEqual(profile)
  })

  it('turns a worker failure into a failed job with the error code', async () => {
    handler = (req, emit) => emit({ id: req.id, ...err(422, 'unreadable_file', 'The file is empty.') })
    const e = await load()
    const { job_id } = await e.startProfile('d1')
    await flush()
    expect(await e.getJob(job_id)).toMatchObject({
      status: 'failed', error: { code: 'unreadable_file', message: 'The file is empty.' },
    })
  })

  it('maps worker errors to ApiError and answers 404 for unknown things', async () => {
    handler = (req, emit) =>
      emit(req.op === 'upload' ? { id: req.id, ok: true, result: upload } : { id: req.id, ...err(404, 'not_found', 'This dataset was not found.') })
    const e = await load()
    await e.uploadDataset(new File(['a'], 'a.csv')).catch(() => {})
    const { ApiError } = await import('./client')
    const caught = await e.getResults('d1').catch((x) => x)
    expect(caught).toBeInstanceOf(ApiError)
    expect(caught).toMatchObject({ status: 404, code: 'not_found' })
    await expect(e.getJob('nope')).rejects.toMatchObject({ status: 404, code: 'not_found' })
    await expect(e.getProfile('nope')).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })

  it('sends results queries as given', async () => {
    handler = (req, emit) => emit({ id: req.id, ok: true, result: req.op === 'upload' ? upload : {} })
    const e = await load()
    await e.uploadDataset(new File(['a'], 'a.csv'))
    await e.getResults('d1', { limit: 5, rule_id: 'r' })
    expect(requests[1]).toMatchObject({ op: 'results', args: { dataset_id: 'd1', query: { limit: 5, rule_id: 'r' } } })
  })

  it('after a clean job, downloads are ready as blob URLs; Excel is built on request', async () => {
    handler = (req, emit) => {
      if (req.op === 'file') {
        return emit({ id: req.id, ok: true, result: { filename: 'a_x', mime: 'text/csv' }, bytes: new Uint8Array([1]) })
      }
      emit({ id: req.id, ok: true, result: {} })
    }
    const e = await load()
    expect(e.downloadUrl('d1', 'clean.csv')).toBe('#')
    const { job_id } = await e.startClean('d1', { approved: ['p1'], rejected: [], edited: [] })
    expect(requests[0]).toMatchObject({ op: 'clean', args: { dataset_id: 'd1', decisions: { approved: ['p1'] } } })
    await flush()
    await flush()
    expect(await e.getJob(job_id)).toMatchObject({ type: 'clean', status: 'done' })
    for (const name of ['clean.csv', 'report.html', 'recipe.yaml', 'changelog.csv']) {
      expect(e.downloadUrl('d1', name)).toMatch(/^blob:/)
    }
    expect(e.downloadUrl('d1', 'clean.xlsx')).toBe('#')
    await expect(e.prepareExcel('d1')).resolves.toEqual({ ready: true })
    expect(e.downloadUrl('d1', 'clean.xlsx')).toMatch(/^blob:/)
    expect(e.downloadName(e.downloadUrl('d1', 'clean.csv'))).toBe('a_x')
  })

  it('a new upload revokes earlier blob URLs and forgets the earlier dataset', async () => {
    let n = 0
    handler = (req, emit) => {
      if (req.op === 'upload') return emit({ id: req.id, ok: true, result: { ...upload, dataset_id: `d${++n}` } })
      if (req.op === 'file') return emit({ id: req.id, ok: true, result: { filename: 'a_x', mime: 'text/csv' }, bytes: new Uint8Array([1]) })
      emit({ id: req.id, ok: true, result: {} })
    }
    const e = await load()
    await e.uploadDataset(new File(['a'], 'a.csv'))
    await e.startClean('d1', { approved: [], rejected: [], edited: [] })
    await flush()
    await flush()
    const url = e.downloadUrl('d1', 'clean.csv')
    expect(url).toMatch(/^blob:/)
    await e.uploadDataset(new File(['b'], 'b.csv'))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(url)
    expect(e.downloadUrl('d1', 'clean.csv')).toBe('#')
    await expect(e.getResults('d1')).rejects.toMatchObject({ status: 404 })
  })

  it('a clean job stays failed when its files cannot be fetched', async () => {
    handler = (req, emit) =>
      emit(req.op === 'file' ? { id: req.id, ...err(500, 'internal_error', 'boom') } : { id: req.id, ok: true, result: {} })
    const e = await load()
    const { job_id } = await e.startClean('d1', { approved: [], rejected: [], edited: [] })
    await flush()
    await flush()
    expect(await e.getJob(job_id)).toMatchObject({ status: 'failed', error: { code: 'internal_error' } })
  })
})
