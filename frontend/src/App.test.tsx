import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getJob, getProfile, getResults } from '@/api/client'
import type { JobStatus, ProfileResponse } from '@/api/types'
import App from './App'

vi.mock('@/api/client', () => ({
  getJob: vi.fn(),
  getProfile: vi.fn(),
  getResults: vi.fn(),
  getHealth: vi.fn().mockResolvedValue({ status: 'ok', max_upload_mb: 4 }),
}))

const job = (over: Partial<JobStatus> = {}): JobStatus =>
  ({ job_id: 'j1', status: 'running', progress_pct: 30, current_step: 'Cleaning columns', error: null, ...over }) as JobStatus
const notFound = () => Object.assign(new Error('Not found'), { status: 404 })

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getJob).mockReset()
  vi.mocked(getProfile).mockReset()
  vi.mocked(getResults).mockReset()
})
afterEach(() => vi.useRealTimers())

const wait = (ms = 2000) => act(() => vi.advanceTimersByTimeAsync(ms))

describe('resume from the URL', () => {
  it('keeps polling a running clean job after the link is reopened', async () => {
    window.history.replaceState(null, '', '/?d=d1&j=j1&s=processing')
    vi.mocked(getJob).mockResolvedValue(job())
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Cleaning your file' })).toBeTruthy()
    await wait()
    expect(getJob).toHaveBeenCalledWith('j1')
    expect(screen.getByText('Cleaning columns (30%)')).toBeTruthy()
  })

  it('does not lose a running job on reload', async () => {
    window.history.replaceState(null, '', '/?d=d1&j=j1&s=processing')
    vi.mocked(getJob).mockResolvedValue(job())
    const first = render(<App />)
    await wait()
    expect(window.location.search).toBe('?d=d1&j=j1&s=processing')
    first.unmount() // the reload
    render(<App />)
    await wait()
    expect(getJob).toHaveBeenCalledTimes(2)
    expect(screen.getByText('Cleaning columns (30%)')).toBeTruthy()
    expect(window.location.search).toBe('?d=d1&j=j1&s=processing')
  })

  it('resumes a running profile job', async () => {
    window.history.replaceState(null, '', '/?d=d1&j=j1&s=profile')
    vi.mocked(getJob).mockResolvedValue(job({ current_step: 'Scanning' }))
    render(<App />)
    await wait()
    expect(screen.getByRole('heading', { name: 'Profiling your file' })).toBeTruthy()
    expect(screen.getByText('Scanning (30%)')).toBeTruthy()
  })

  it('loads the finished profile for the Suggested fixes screen', async () => {
    window.history.replaceState(null, '', '/?d=d1&s=fixes')
    vi.mocked(getProfile).mockResolvedValue({ proposals: [], columns: [] } as unknown as ProfileResponse)
    render(<App />)
    expect(screen.getByText(/Loading your file/)).toBeTruthy()
    await wait(0)
    expect(getProfile).toHaveBeenCalledWith('d1')
    expect(screen.queryByText(/Loading your file/)).toBeNull()
    expect(getJob).not.toHaveBeenCalled()
  })

  it('loads finished results for the Results screen', async () => {
    window.history.replaceState(null, '', '/?d=d1&j=j1&s=results')
    vi.mocked(getResults).mockRejectedValue(notFound())
    render(<App />)
    await wait(0)
    expect(getResults).toHaveBeenCalledWith('d1', { limit: 50 })
    expect(getJob).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toBe('This result has expired. Please upload the file again.')
  })

  it('shows the expired message for an unknown profile and clears the URL on Upload another file', async () => {
    window.history.replaceState(null, '', '/?d=gone&s=fixes')
    vi.mocked(getProfile).mockRejectedValue(notFound())
    render(<App />)
    await wait(0)
    expect(screen.getByRole('alert').textContent).toMatch(/has expired/)
    act(() => screen.getByRole('button', { name: 'Upload another file' }).click())
    expect(screen.getByRole('heading', { name: 'Upload your file' })).toBeTruthy()
    expect(window.location.search).toBe('')
  })

  it('starts on Upload when the URL has no ids or has junk', () => {
    window.history.replaceState(null, '', '/?d=../x&s=results')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Upload your file' })).toBeTruthy()
  })

  it('focuses the expired message after a failed restore', async () => {
    window.history.replaceState(null, '', '/?d=gone&s=fixes')
    vi.mocked(getProfile).mockRejectedValue(notFound())
    render(<App />)
    await wait(0)
    expect(document.activeElement).toBe(screen.getByRole('alert'))
  })
})
