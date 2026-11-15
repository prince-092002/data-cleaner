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
  left_alone: [],
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
  prop({
    id: 'e',
    title: 'Categories',
    severity: 'low',
    rule_id: 'standardize_categories',
    column: 'region',
    is_destructive: true,
    params: { tier: 2, mapping: { Wst: 'West' }, reasons: { Wst: '"Wst" is one letter away from "West"' } },
    editable_params: ['mapping'],
    left_alone: [{ value: 'Zed', count: 2, reason: '"Zed" does not look like a typo' }],
  }),
  prop({
    id: 'h',
    title: 'Case merges',
    rule_id: 'standardize_categories',
    column: 'region',
    mode: 'auto',
    is_destructive: true,
    params: { tier: 1, mapping: { WEST: 'West', west: 'West' } },
    editable_params: ['mapping'],
  }),
  prop({
    id: 'k',
    title: 'Case suggestion',
    rule_id: 'standardize_categories',
    column: 'region',
    is_destructive: true,
    params: {
      case_suggestion: true,
      mapping: { NORTH: 'North' },
      reasons: { NORTH: 'No spelling is used in 80% of rows, so the Title Case spelling "North" is suggested' },
    },
    editable_params: ['mapping'],
  }),
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
  prop({
    id: 'n',
    title: 'Name capitals',
    column: 'customer_name',
    params: { name_case: true, mapping: { 'JOHN SMITH': 'John Smith' } },
  }),
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
  it('groups fixes by column', () => {
    setup()
    const col = (name: string) =>
      screen.getByRole('region', { name: new RegExp(`^Column ${name} \\(`) })
    expect(within(col('c')).getAllByTestId('proposal-card')).toHaveLength(5)
    expect(within(col('amb')).getByRole('heading', { name: 'Ambiguous dates' })).toBeInTheDocument()
    expect(within(col('region')).getByRole('heading', { name: 'Categories' })).toBeInTheDocument()
    expect(within(card('Auto fix')).getByText('(empty)')).toBeInTheDocument()
  })

  it('shows each suggested merge with its reason', () => {
    setup()
    const c = within(card('Categories'))
    expect(c.getByText('"Wst" is one letter away from "West"')).toBeInTheDocument()
  })

  it('a no-majority case suggestion is a normal card with its reason, not an automatic merge', async () => {
    const u = userEvent.setup()
    setup()
    const auto = within(screen.getByRole('region', { name: 'Automatic merges' }))
    expect(auto.queryByRole('button', { name: 'Undo merge of NORTH into North' })).not.toBeInTheDocument()
    const region = within(screen.getByRole('region', { name: /^Column region/ }))
    expect(region.getByRole('heading', { name: 'Case suggestion' })).toBeInTheDocument()
    expect(
      within(card('Case suggestion')).getByText(
        'No spelling is used in 80% of rows, so the Title Case spelling "North" is suggested',
      ),
    ).toBeInTheDocument()
    expect(status('Case suggestion')).toBe('Undecided (will not run)')
    await u.click(screen.getByRole('button', { name: 'Approve all safe fixes' }))
    expect(status('Case suggestion')).toBe('Undecided (will not run)')
  })

  it('lists values left alone with a count and reason', () => {
    setup()
    const left = within(screen.getByRole('region', { name: /^Column region/ }))
    expect(left.getByText('Zed')).toBeInTheDocument()
    expect(left.getByText('"Zed" does not look like a typo')).toBeInTheDocument()
  })

  it('automatic merges have their own section with an Undo per merge', async () => {
    const u = userEvent.setup()
    vi.mocked(startClean).mockResolvedValue({ job_id: 'j2' })
    setup()
    const auto = within(screen.getByRole('region', { name: 'Automatic merges' }))
    expect(screen.queryByRole('heading', { name: 'Case merges' })).not.toBeInTheDocument()
    await u.click(auto.getByRole('button', { name: 'Undo merge of WEST into West' }))
    expect(auto.getByRole('button', { name: 'Redo merge of WEST into West' })).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Start cleaning' }))
    expect(startClean).toHaveBeenCalledWith('d1', {
      approved: ['a', 'h'],
      rejected: [],
      edited: [{ id: 'h', params: { tier: 1, mapping: { west: 'West' } } }],
    })
  })

  it('undoing every automatic merge rejects that fix', async () => {
    const u = userEvent.setup()
    vi.mocked(startClean).mockResolvedValue({ job_id: 'j3' })
    setup()
    const auto = within(screen.getByRole('region', { name: 'Automatic merges' }))
    await u.click(auto.getByRole('button', { name: 'Undo merge of WEST into West' }))
    await u.click(auto.getByRole('button', { name: 'Undo merge of west into West' }))
    await u.click(screen.getByRole('button', { name: 'Start cleaning' }))
    expect(startClean).toHaveBeenCalledWith('d1', { approved: ['a'], rejected: ['h'], edited: [] })
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
    expect(status('Name capitals')).toBe('Undecided (will not run)')
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
      approved: ['a', 'b', 'h'],
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
    expect(startClean).toHaveBeenCalledWith('d1', { approved: ['a', 'h'], rejected: ['c'], edited: [] })
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
