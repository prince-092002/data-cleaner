import { act, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getJob, getResults } from '@/api/client'
import type { JobStatus, ResultsResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { ProcessingScreen } from './ProcessingScreen'

vi.mock('@/api/client', () => ({ getJob: vi.fn(), getResults: vi.fn() }))

const job = (over: Partial<JobStatus>): JobStatus =>
  ({ job_id: 'j1', status: 'running', progress_pct: 20, current_step: 'Reading', error: null, ...over }) as JobStatus

function Probe() {
  const { state } = useAppState()
  return <p data-testid="probe">{`${state.step}|${state.results ? 'results' : 'none'}`}</p>
}

function Seed({ withJob = true }: { withJob?: boolean }) {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1' } as UploadResponse })
    if (withJob) dispatch({ type: 'job_started', jobId: 'j1' })
    dispatch({ type: 'goto', step: 3 })
    setReady(true)
  }, [dispatch, withJob])
  return ready ? (
    <>
      <ProcessingScreen />
      <Probe />
    </>
  ) : null
}

function setup(withJob = true) {
  return render(
    <AppStateProvider>
      <Seed withJob={withJob} />
    </AppStateProvider>,
  )
}

const tick = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(2000)
  })

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getJob).mockReset()
  vi.mocked(getResults).mockReset()
})
afterEach(() => vi.useRealTimers())

describe('ProcessingScreen', () => {
  it('updates progress across polls', async () => {
    vi.mocked(getJob)
      .mockResolvedValueOnce(job({ progress_pct: 20, current_step: 'Reading' }))
      .mockResolvedValueOnce(job({ progress_pct: 60, current_step: 'Working' }))
    setup()
    await tick()
    expect(screen.getByText('Reading (20%)')).toBeTruthy()
    await tick()
    expect(screen.getByText('Working (60%)')).toBeTruthy()
    expect(getJob).toHaveBeenCalledTimes(2)
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('loads results and goes to step 4 when done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockResolvedValue({ run_id: 'j1' } as unknown as ResultsResponse)
    setup()
    await tick()
    expect(getResults).toHaveBeenCalledWith('d1', { limit: 50 })
    expect(screen.getByTestId('probe').textContent).toBe('4|results')
  })

  it('shows the failure message and buttons', async () => {
    vi.mocked(getJob).mockResolvedValue(
      job({ status: 'failed', error: { code: 'internal_error', message: 'Boom happened' } }),
    )
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('Boom happened')
    act(() => screen.getByRole('button', { name: 'Back to suggested fixes' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('2|none')
  })

  it('shows a friendlier line for interrupted jobs and can try another file', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'interrupted', message: 'raw' } }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toMatch(/server restarted/)
    act(() => screen.getByRole('button', { name: 'Try another file' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('0|none')
  })

  it('shows an error with buttons when loading results fails after done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockImplementation(() => Promise.reject(new Error('Results unavailable')))
    setup()
    await tick()
    await tick()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('Results unavailable')
    expect(screen.getByRole('button', { name: 'Try another file' })).toBeTruthy()
  })

  it('clears the interval on unmount', async () => {
    vi.mocked(getJob).mockResolvedValue(job({}))
    const { unmount } = setup()
    await tick()
    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(getJob).toHaveBeenCalledTimes(1)
  })

  it('offers a way back when there is no job', () => {
    setup(false)
    expect(screen.getByRole('button', { name: 'Back to suggested fixes' })).toBeTruthy()
    expect(getJob).not.toHaveBeenCalled()
  })

  it('shows a waiting state while the job is queued', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'queued', progress_pct: 0, current_step: 'Queued' }))
    setup()
    await tick()
    expect(screen.getByText(/Waiting to start/)).toBeTruthy()
    expect(screen.queryByText(/^Queued/)).toBeNull()
  })

  it('shows the step and percentage while running', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ progress_pct: 45, current_step: 'Applying fixes' }))
    setup()
    await tick()
    expect(screen.getByText('Applying fixes (45%)')).toBeTruthy()
    expect(screen.queryByText(/Waiting to start/)).toBeNull()
  })

  it('shows the timeout message with a way back to Upload', async () => {
    vi.mocked(getJob).mockResolvedValue(
      job({ status: 'failed', error: { code: 'job_timeout', message: 'This file took too long to process. Try a smaller file.' } }),
    )
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('This file took too long to process. Try a smaller file.')
    act(() => screen.getByRole('button', { name: 'Try another file' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('0|none')
  })

  it('falls back to a plain timeout message when the server sends none', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'job_timeout' } as JobStatus['error'] }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toMatch(/took too long/)
  })

  it('shows the expired message for a failed job with code expired', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'expired', message: 'raw' } }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('This result has expired. Please upload the file again.')
    act(() => screen.getByRole('button', { name: 'Upload another file' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('0|none')
  })

  it('shows the expired message when the job is a 404', async () => {
    vi.mocked(getJob).mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('This result has expired. Please upload the file again.')
  })

  it('shows the expired message when the results are a 404', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toMatch(/has expired/)
  })

  it('does not show an error after two failed polls followed by a success', async () => {
    vi.mocked(getJob)
      .mockRejectedValueOnce(new Error('blip'))
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValue(job({ progress_pct: 30, current_step: 'Working' }))
    setup()
    await tick()
    await tick()
    await tick()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByText('Working (30%)')).toBeTruthy()
  })

  it('shows the error after three failed polls in a row', async () => {
    vi.mocked(getJob).mockRejectedValue(new Error('Server down'))
    setup()
    await tick()
    await tick()
    expect(screen.queryByRole('alert')).toBeNull()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('Server down')
    expect(getJob).toHaveBeenCalledTimes(3)
  })

  it('polls every 2 s, then every 5 s after a minute', async () => {
    vi.mocked(getJob).mockResolvedValue(job({}))
    setup()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(getJob).toHaveBeenCalledTimes(30)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(getJob).toHaveBeenCalledTimes(32)
  })

  it('stops polling once the job is done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockResolvedValue({ run_id: 'j1' } as unknown as ResultsResponse)
    setup()
    await tick()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })
    expect(getJob).toHaveBeenCalledTimes(1)
  })

  it('moves keyboard focus to the message when the job fails', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'internal_error', message: 'Boom' } }))
    setup()
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('alert'))
  })

  it('moves keyboard focus to the message when the result has expired', async () => {
    vi.mocked(getJob).mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }))
    setup()
    await tick()
    expect(document.activeElement).toBe(screen.getByRole('alert'))
  })
})
