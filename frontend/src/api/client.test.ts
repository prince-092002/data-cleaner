import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  downloadUrl,
  getJob,
  getResults,
  resultsQueryString,
  startClean,
  uploadDataset,
} from './client'

function mockFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  const fn = vi.fn(impl)
  vi.stubGlobal('fetch', fn)
  return fn
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('returns parsed JSON on success', async () => {
    const job = { job_id: 'j1', status: 'running', progress_pct: 40 }
    const f = mockFetch(async () => json(job))
    await expect(getJob('j1')).resolves.toEqual(job)
    expect(f.mock.calls[0][0]).toBe('/api/jobs/j1')
  })

  it('uploads as multipart with field "file"', async () => {
    const f = mockFetch(async () => json({ dataset_id: 'd1' }, 201))
    await uploadDataset(new File(['a,b'], 'x.csv'))
    const init = f.mock.calls[0][1]!
    expect(init.method).toBe('POST')
    expect((init.body as FormData).get('file')).toBeInstanceOf(File)
  })

  it('posts decisions as JSON', async () => {
    const f = mockFetch(async () => json({ job_id: 'j2' }, 202))
    const decisions = { approved: ['sug_1'], rejected: [], edited: [] }
    await startClean('d1', decisions)
    expect(f.mock.calls[0][0]).toBe('/api/datasets/d1/clean')
    expect(JSON.parse(f.mock.calls[0][1]!.body as string)).toEqual(decisions)
  })

  it('throws ApiError parsed from the error body', async () => {
    mockFetch(async () =>
      json({ error: { code: 'file_too_large', message: 'Files must be 50 MB or smaller.' } }, 413),
    )
    const err = await uploadDataset(new File(['x'], 'big.csv')).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({
      status: 413,
      code: 'file_too_large',
      message: 'Files must be 50 MB or smaller.',
    })
  })

  it('falls back to a generic ApiError when the body is not JSON', async () => {
    mockFetch(async () => new Response('<html>oops</html>', { status: 502 }))
    const err = await getJob('j1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(502)
    expect(err.code).toBe('internal_error')
  })

  it('turns a network failure into a friendly ApiError', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })
    const err = await getJob('j1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
    expect(err.code).toBe('network_error')
    expect(err.message).toMatch(/could not reach the server/i)
  })

  it('builds the results query string and skips empty values', () => {
    expect(resultsQueryString()).toBe('')
    expect(resultsQueryString({ limit: 50, offset: 100, rule_id: 'parse_dates', column: '' })).toBe(
      '?limit=50&offset=100&rule_id=parse_dates',
    )
    expect(resultsQueryString({ offset: 0, action: 'approved', change_type: 'cell' })).toBe(
      '?offset=0&action=approved&change_type=cell',
    )
  })

  it('getResults sends the filters', async () => {
    const f = mockFetch(async () => json({ dataset_id: 'd1' }))
    await getResults('d1', { limit: 25, column: 'order date' })
    expect(f.mock.calls[0][0]).toBe('/api/datasets/d1/results?limit=25&column=order+date')
  })

  it('builds download URLs', () => {
    expect(downloadUrl('d1', 'clean.csv')).toBe('/api/datasets/d1/downloads/clean.csv')
  })

  it.each([
    [413, 'file_too_large', /too large/],
    [429, 'too_many_jobs', /Too many files/],
    [503, 'storage_full', /demo is full/],
  ])('gives a friendly message for %i when the server sends none', async (status, code, text) => {
    mockFetch(async () => new Response('', { status }))
    await expect(startClean('d1', { approved: [], rejected: [], edited: [] })).rejects.toMatchObject({ status, message: expect.stringMatching(text) })
    expect(code).toBeTruthy()
  })

  it("keeps the server's own message and code for 429 and 503", async () => {
    mockFetch(async () => json({ error: { code: 'storage_full', message: 'The demo is full right now. Please try again tomorrow.' } }, 503))
    await expect(uploadDataset(new File(['a'], 'x.csv'))).rejects.toMatchObject({
      status: 503,
      code: 'storage_full',
      message: 'The demo is full right now. Please try again tomorrow.',
    })
  })
})
