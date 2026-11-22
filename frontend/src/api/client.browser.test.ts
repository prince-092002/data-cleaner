import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./browserEngine', () => ({
  getHealth: vi.fn(async () => ({ status: 'ok', max_upload_mb: 20 })),
  uploadDataset: vi.fn(),
  startProfile: vi.fn(async () => ({ job_id: 'b1' })),
  getJob: vi.fn(),
  getProfile: vi.fn(),
  startClean: vi.fn(),
  getResults: vi.fn(),
  prepareExcel: vi.fn(),
  downloadUrl: vi.fn(() => 'blob:x'),
  downloadName: vi.fn(() => 'x_clean.csv'),
}))

import * as browser from './browserEngine'
import { downloadUrl, getHealth, startDownload, startProfile } from './client'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('VITE_ENGINE switch', () => {
  it('uses the server when VITE_ENGINE is not "browser"', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ job_id: 's1' }), { status: 202 }))
    vi.stubGlobal('fetch', f)
    await expect(startProfile('d1')).resolves.toEqual({ job_id: 's1' })
    expect(f).toHaveBeenCalled()
    expect(browser.startProfile).not.toHaveBeenCalled()
    expect(downloadUrl('d1', 'clean.csv')).toBe('/api/datasets/d1/downloads/clean.csv')
  })

  it('uses the in-browser engine when VITE_ENGINE is "browser"', async () => {
    vi.stubEnv('VITE_ENGINE', 'browser')
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    await expect(startProfile('d1', { header_row: 1 })).resolves.toEqual({ job_id: 'b1' })
    expect(browser.startProfile).toHaveBeenCalledWith('d1', { header_row: 1 })
    await expect(getHealth()).resolves.toMatchObject({ max_upload_mb: 20 })
    expect(downloadUrl('d1', 'clean.csv')).toBe('blob:x')
    expect(f).not.toHaveBeenCalled()
  })

  it('names the saved file after the download, not the blob id', () => {
    vi.stubEnv('VITE_ENGINE', 'browser')
    let saved = ''
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved = this.download
    })
    startDownload('blob:x')
    expect(saved).toBe('x_clean.csv')
    click.mockRestore()
  })
})
