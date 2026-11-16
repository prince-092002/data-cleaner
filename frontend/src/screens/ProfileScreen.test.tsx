import { act, render, screen } from '@testing-library/react'
import { useEffect, useState, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getJob, getProfile } from '@/api/client'
import type { ColumnProfile, JobStatus, ProfileResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { ProfileScreen } from './ProfileScreen'

vi.mock('@/api/client', () => ({ getJob: vi.fn(), getProfile: vi.fn() }))

const q = { overall: 82, completeness: 90, validity: 80, consistency: 70, uniqueness: 100, conformity: 60 }
const col = (name: string, position: number): ColumnProfile =>
  ({
    name,
    position,
    inferred_type: 'integer',
    null_pct: 12.5,
    distinct_count: 7,
    samples: ['a', 'b'],
    issues: [{ code: 'whitespace', severity: 'low', message: 'm', count: 2 }],
  }) as unknown as ColumnProfile
const profile = {
  dataset_id: 'd1',
  source: { filename: 'people.csv' },
  row_count: 100,
  column_count: 2,
  quality: q,
  columns: [col('age', 0), col('city', 1)],
} as unknown as ProfileResponse
const upload = { dataset_id: 'd1' } as UploadResponse
const job = (over: Partial<JobStatus>): JobStatus =>
  ({ job_id: 'j1', status: 'running', progress_pct: 40, current_step: 'Scanning', error: null, ...over }) as JobStatus

let current: ProfileResponse = profile

function Seed({ withProfile, children }: { withProfile?: boolean; children: ReactNode }) {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload })
    dispatch({ type: 'job_started', jobId: 'j1' })
    if (withProfile) dispatch({ type: 'profile_loaded', profile: current })
    setReady(true)
  }, [dispatch, withProfile])
  return ready ? <>{children}</> : null
}

function setup(withProfile = false) {
  render(
    <AppStateProvider>
      <Seed withProfile={withProfile}>
        <ProfileScreen />
      </Seed>
    </AppStateProvider>,
  )
}

beforeEach(() => {
  current = profile
  vi.useFakeTimers()
  vi.mocked(getJob).mockReset()
  vi.mocked(getProfile).mockReset()
})
afterEach(() => vi.useRealTimers())

describe('ProfileScreen', () => {
  it('polls until done then renders score and column cards', async () => {
    vi.mocked(getJob)
      .mockResolvedValueOnce(job({}))
      .mockResolvedValueOnce(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getProfile).mockResolvedValue(profile)
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByText(/Scanning/)).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(getProfile).toHaveBeenCalledWith('d1')
    expect(screen.getByTestId('overall-score').textContent).toContain('82')
    expect(screen.getAllByTestId('column-card')).toHaveLength(2)
    expect(screen.getAllByTitle('whitespace')).toHaveLength(2)
    expect(screen.getByText('Continue to suggested fixes')).toBeTruthy()
  })

  it('shows the error for a failed job', async () => {
    vi.mocked(getJob).mockResolvedValue(
      job({ status: 'failed', error: { code: 'unreadable_file', message: 'Bad file' } }),
    )
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByRole('alert').textContent).toBe('Bad file')
    expect(screen.getByText('Back to upload')).toBeTruthy()
  })

  it('shows an error when loading the profile fails after done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getProfile).mockImplementation(() => Promise.reject(new Error('Profile unavailable')))
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByRole('alert').textContent).toBe('Profile unavailable')
    expect(screen.getByText('Back to upload')).toBeTruthy()
  })

  it('shows friendly wording for interrupted jobs', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'interrupted', message: 'raw' } }))
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByRole('alert').textContent).toMatch(/server restarted/)
  })

  const withSource = (source: object) =>
    ({ ...profile, source: { filename: 'people.csv', ...source } }) as unknown as ProfileResponse

  it('shows encoding and delimiter for csv without the note for utf-8', () => {
    current = withSource({ file_type: 'csv', encoding: 'utf-8', delimiter: ';' })
    setup(true)
    expect(screen.getByText('Encoding: utf-8')).toBeTruthy()
    expect(screen.getByText('Delimiter: semicolon')).toBeTruthy()
    expect(screen.queryByText(/read as Windows-1252/)).toBeNull()
  })

  it('shows the note for windows-1252', () => {
    current = withSource({ file_type: 'csv', encoding: 'windows-1252', delimiter: ',' })
    setup(true)
    expect(screen.getByText('Encoding: windows-1252')).toBeTruthy()
    expect(screen.getByText(/Latin-script files are read as Windows-1252/)).toBeTruthy()
  })

  it('shows no encoding for xlsx', () => {
    current = withSource({ file_type: 'xlsx', encoding: null, delimiter: null })
    setup(true)
    expect(screen.getByText('Excel file')).toBeTruthy()
    expect(screen.queryByText(/Encoding/)).toBeNull()
  })

  it('skips polling when the profile is already in state', async () => {
    setup(true)
    await act(() => vi.advanceTimersByTimeAsync(6000))
    expect(getJob).not.toHaveBeenCalled()
    expect(screen.getAllByTestId('column-card')).toHaveLength(2)
  })

  it('shows a waiting state while the profile job is queued', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'queued', progress_pct: 0, current_step: 'Queued' }))
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByText(/Waiting to start/)).toBeTruthy()
  })

  it('shows the expired message when the job is a 404', async () => {
    vi.mocked(getJob).mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 }))
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByRole('alert').textContent).toBe('This result has expired. Please upload the file again.')
  })

  it('shows the timeout message from the server', async () => {
    vi.mocked(getJob).mockResolvedValue(
      job({ status: 'failed', error: { code: 'job_timeout', message: 'This file took too long to process. Try a smaller file.' } }),
    )
    setup()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByRole('alert').textContent).toMatch(/took too long/)
  })
})
