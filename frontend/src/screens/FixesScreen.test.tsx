import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { startClean } from '@/api/client'
import type { Proposal, ProfileResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { FixesScreen } from './FixesScreen'

vi.mock('@/api/client', () => {
  class ApiError extends Error {}
  return { startClean: vi.fn(), ApiError }
})

const prop = (over: Partial<Proposal>): Proposal => ({
  id: 'x',
  rule_id: 'trim_and_normalize_text',
  rule_version: '1',
  column: 'c',
  mode: 'suggest',
  severity: 'medium',
  is_destructive: false,
  confidence: 0.9,
  title: 'T',
  description: 'D',
  rows_affected: 3,
  params: {},
  editable_params: [],
  samples: [{ row_id: 1, before: null, after: 'a' }],
  ...over,
})
const proposals = [
  prop({ id: 'a', title: 'Auto fix', mode: 'auto', severity: 'high' }),
  prop({
    id: 'b',
    title: 'Dates',
    rule_id: 'parse_dates',
    severity: 'high',
    params: { dayfirst: false },
    editable_params: ['dayfirst'],
  }),
  prop({ id: 'c', title: 'Dedupe', severity: 'medium', is_destructive: true }),
  prop({ id: 'd', title: 'Outliers', severity: 'low', mode: 'flag' }),
  prop({ id: 'e', title: 'Categories', severity: 'low', rule_id: 'standardize_categories' }),
  prop({
    id: 'f',
    title: 'Ambiguous dates',
    rule_id: 'parse_dates',
    column: 'amb',
    severity: 'high',
    params: { dayfirst: false },
    editable_params: ['dayfirst'],
  }),
  prop({ id: 'g', title: 'Trim', severity: 'medium' }),
]
const profile = {
  proposals,
  columns: [{ name: 'amb', issues: [{ code: 'ambiguous_dates' }] }],
} as unknown as ProfileResponse

function Probe() {
  const { state } = useAppState()
  return (
    <output data-testid="step">
      {state.step}:{state.jobId}
    </output>
  )
}
let seedRunning = false
function Seed() {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1' } as UploadResponse })
    dispatch({ type: 'profile_loaded', profile })
    dispatch({ type: 'goto', step: 2 })
    if (seedRunning) dispatch({ type: 'job_started', jobId: 'j0' })
    setReady(true)
  }, [dispatch])
  return ready ? (
    <>
      <FixesScreen />
      <Probe />
    </>
  ) : null
}
const setup = () =>
  render(
    <AppStateProvider>
      <Seed />
    </AppStateProvider>,
  )
const card = (title: string) =>
  screen.getByRole('heading', { name: title }).closest('[data-testid="proposal-card"]') as HTMLElement
const status = (title: string) => within(card(title)).getByTestId('status').textContent

beforeEach(() => {
  seedRunning = false
  vi.mocked(startClean).mockReset()
})

describe('FixesScreen', () => {
  it('groups by severity with counts', () => {
    setup()
    expect(screen.getByRole('heading', { name: 'High severity (3)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Medium severity (2)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Low severity (2)' })).toBeInTheDocument()
    expect(within(card('Auto fix')).getByText('(empty)')).toBeInTheDocument()
  })

  it('auto starts approved; approve and reject toggle', async () => {
    const u = userEvent.setup()
    setup()
    expect(status('Auto fix')).toBe('Approved')
    expect(status('Dedupe')).toBe('Undecided (will not run)')
    const reject = within(card('Dedupe')).getByRole('button', { name: 'Reject' })
    await u.click(reject)
    expect(reject).toHaveAttribute('aria-pressed', 'true')
    expect(status('Dedupe')).toBe('Rejected')
    await u.click(within(card('Dedupe')).getByRole('button', { name: 'Approve' }))
    expect(status('Dedupe')).toBe('Approved')
    expect(reject).toHaveAttribute('aria-pressed', 'false')
  })

  it('approve all safe skips destructive, flag-only, categories and ambiguous dates', async () => {
    const u = userEvent.setup()
    setup()
    await u.click(screen.getByRole('button', { name: 'Approve all safe fixes' }))
    expect(status('Dates')).toBe('Approved')
    expect(status('Trim')).toBe('Approved')
    expect(status('Categories')).toBe('Undecided (will not run)')
    expect(status('Ambiguous dates')).toBe('Undecided (will not run)')
    expect(status('Dedupe')).toBe('Undecided (will not run)')
    expect(status('Outliers')).toBe('Runs unless rejected')
  })

  it('ambiguous Approve is disabled until a date order is chosen', async () => {
    const u = userEvent.setup()
    setup()
    const c = within(card('Ambiguous dates'))
    expect(c.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(c.getByText('Choose day-first or month-first first')).toBeInTheDocument()
    await u.click(c.getByRole('button', { name: 'Month first' }))
    expect(c.getByRole('button', { name: 'Approve' })).toBeEnabled()
    expect(c.queryByText('Choose day-first or month-first first')).not.toBeInTheDocument()
    expect(status('Ambiguous dates')).toBe('Approved')
  })

  it('editing dayfirst yields an edited entry', async () => {
    const u = userEvent.setup()
    vi.mocked(startClean).mockResolvedValue({ job_id: 'j9' })
    setup()
    await u.click(within(card('Dates')).getByRole('button', { name: 'Edit' }))
    await u.click(screen.getByRole('radio', { name: /Day first/ }))
    await u.click(screen.getByRole('button', { name: 'Save and approve' }))
    expect(status('Dates')).toBe('Approved')
    await u.click(screen.getByRole('button', { name: 'Start cleaning' }))
    expect(startClean).toHaveBeenCalledWith('d1', {
      approved: ['a', 'b'],
      rejected: [],
      edited: [{ id: 'b', params: { dayfirst: true } }],
    })
  })

  it('Start cleaning sends decisions and moves to processing', async () => {
    const u = userEvent.setup()
    vi.mocked(startClean).mockResolvedValue({ job_id: 'j1' })
    setup()
    await u.click(within(card('Dedupe')).getByRole('button', { name: 'Reject' }))
    await u.click(screen.getByRole('button', { name: 'Start cleaning' }))
    expect(startClean).toHaveBeenCalledWith('d1', { approved: ['a'], rejected: ['c'], edited: [] })
    expect(await screen.findByText('3:j1')).toBeInTheDocument()
  })

  it('disables Start cleaning while a job is running', () => {
    seedRunning = true
    setup()
    expect(screen.getByRole('button', { name: 'Start cleaning' })).toBeDisabled()
    expect(screen.getByText('A job is still running. Wait for it to finish.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve all safe fixes' })).toBeEnabled()
  })
})
