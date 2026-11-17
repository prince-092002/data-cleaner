import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '@/api/client'

const getResults = (client as unknown as { __spy: ReturnType<typeof vi.fn> }).__spy
import type { ChangesPage, QualityScore, ResultsResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { ResultsScreen } from './ResultsScreen'

// vitest flags rejections that pass through a vi.fn as unhandled, so the failing case bypasses the spy.
const hoisted = vi.hoisted(() => ({ fail: false }))
vi.mock('@/api/client', () => {
  const spy = vi.fn()
  return {
    getResults: (...args: unknown[]) =>
      hoisted.fail ? Promise.reject(new Error('boom')) : (spy as (...a: unknown[]) => unknown)(...args),
    __spy: spy,
  }
})

const q = (n: number): QualityScore => ({ overall: n, completeness: n, validity: n, consistency: n, uniqueness: n, conformity: n })
const page = (total: number, offset = 0): ChangesPage => ({
  total,
  limit: 50,
  offset,
  items: [
    { run_id: 'r', rule_id: 'coerce_numeric', rule_version: '1', row_id: 3, column: 'price', change_type: 'cell', old_value: '1,5', new_value: '1.5', action: 'auto', timestamp: 't' },
  ],
})
const results = (over: Partial<ResultsResponse> = {}): ResultsResponse => ({
  dataset_id: 'd1',
  run_id: 'r',
  before: q(60),
  after: q(90.5),
  columns: [
    { name: 'price', before: { score: 50 } as never, after: { score: 95 } as never },
    { name: 'new_col', before: null, after: { score: 100 } as never },
    { name: 'old_col', before: { score: 10 } as never, after: null },
  ],
  summary: {
    total_changes: 120, cells_changed: 100, rows_removed: 5, columns_removed: 1, columns_added: 2,
    rows_before: 200, rows_after: 195, columns_before: 5, columns_after: 6,
    by_rule: [{ rule_id: 'coerce_numeric', action: 'auto', changes: 100, columns: ['price'] }],
  },
  changes: page(120),
  downloads: [],
  warnings: [],
  ...over,
})

function Seed({ res }: { res: ResultsResponse | null }) {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1' } as UploadResponse })
    if (res) dispatch({ type: 'results_loaded', results: res })
    dispatch({ type: 'goto', step: 4 })
    setReady(true)
  }, [dispatch, res])
  return ready ? <ResultsScreen /> : null
}
const setup = (res: ResultsResponse | null = results()) =>
  render(
    <AppStateProvider>
      <Seed res={res} />
    </AppStateProvider>,
  )

beforeEach(() => {
  hoisted.fail = false
  getResults.mockReset()
})

describe('ResultsScreen', () => {
  it('renders scores, tiles, warnings and column new/removed', () => {
    setup(results({ warnings: ['Careful'] }))
    expect(screen.getByTestId('headline').textContent).toMatch(/60 -> 90\.5.*\+30\.5/)
    expect(screen.getAllByTestId('tile')).toHaveLength(4)
    expect(screen.getByText('200 -> 195 (5 removed)')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toMatch(/Careful/)
    const rows = screen.getAllByTestId('column-row')
    expect(rows[1].textContent).toMatch(/new/)
    expect(rows[2].textContent).toMatch(/removed/)
    expect(screen.getByText('Showing 1-1 of 120')).toBeTruthy()
  })

  it('shows before, after and change for overall and five dimensions', () => {
    setup(results({ before: { ...q(60), validity: 70 }, after: { ...q(90.5), validity: 68.96, uniqueness: 60 } }))
    const rows = screen.getAllByTestId('dimension-row')
    expect(rows).toHaveLength(6)
    expect(rows[0].textContent).toMatch(/Overall/)
    expect(rows[0].textContent).toMatch(/60\.090\.5\+30\.5up 30\.5/)
    expect(rows[2].textContent).toMatch(/Validity.*70.069.0-1\.0down 1\.0/)
    expect(rows[4].textContent).toMatch(/unchanged/)
    expect(rows[5].textContent).toMatch(/up 30\.5/)
  })

  it('shows a message when there are no results', () => {
    setup(null)
    expect(screen.getByText(/No results are available/)).toBeTruthy()
  })

  it('filter change calls getResults with offset 0', async () => {
    getResults.mockResolvedValue(results({ changes: page(120) }))
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(getResults).toHaveBeenLastCalledWith('d1', { limit: 50, offset: 50 }))
    fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'approved' } })
    await waitFor(() =>
      expect(getResults).toHaveBeenLastCalledWith('d1', { limit: 50, offset: 0, action: 'approved' }),
    )
  })

  it('waits 300 ms after the last keystroke before filtering by column', () => {
    vi.useFakeTimers()
    try {
      getResults.mockResolvedValue(results({ changes: page(120) }))
      setup()
      const input = screen.getByLabelText('Column')
      for (const v of ['p', 'pr', 'pri']) {
        fireEvent.change(input, { target: { value: v } })
        act(() => void vi.advanceTimersByTime(200))
      }
      expect(getResults).not.toHaveBeenCalled()
      act(() => void vi.advanceTimersByTime(100))
      expect(getResults).toHaveBeenCalledTimes(1)
      expect(getResults).toHaveBeenCalledWith('d1', { limit: 50, offset: 0, column: 'pri' })
    } finally {
      vi.useRealTimers()
    }
  })

  it('pages by the initial page limit so page 2 does not repeat rows', async () => {
    getResults.mockResolvedValue(results({ changes: page(250, 100) }))
    setup(results({ changes: { ...page(250), limit: 100 } }))
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(getResults).toHaveBeenCalledWith('d1', { limit: 100, offset: 100 }))
  })

  it('next page uses offset 50', async () => {
    getResults.mockResolvedValue(results({ changes: page(120, 50) }))
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(getResults).toHaveBeenCalledWith('d1', { limit: 50, offset: 50 }))
    await waitFor(() => expect(screen.getByText('Showing 51-51 of 120')).toBeTruthy())
  })

  it('shows 11-column change records (with reason) from the server', async () => {
    const withReason: ChangesPage = {
      total: 2,
      limit: 50,
      offset: 0,
      items: [
        { run_id: 'r', rule_id: 'standardize_categories', rule_version: '1.2.0', row_id: 7, column: 'city', change_type: 'cell', old_value: 'Chicago', new_value: 'CHICAGO', action: 'auto', timestamp: 't', reason: 'majority spelling' },
        { run_id: 'r', rule_id: 'parse_dates', rule_version: '1', row_id: 8, column: 'day', change_type: 'cell', old_value: '1/2/24', new_value: '2024-01-02', action: 'approved', timestamp: 't', reason: null },
      ],
    }
    getResults.mockResolvedValue(results({ changes: withReason }))
    setup()
    fireEvent.change(screen.getByLabelText('Rule'), { target: { value: 'coerce_numeric' } })
    await waitFor(() => expect(screen.getByText('Showing 1-2 of 2')).toBeTruthy())
    const rows = screen.getAllByTestId('change-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toMatch(/city.*standardize_categories.*Chicago.*CHICAGO.*auto/)
    expect(rows[1].textContent).toMatch(/day.*parse_dates.*1\/2\/24.*2024-01-02.*approved/)
  })

  it('shows an error state', async () => {
    hoisted.fail = true
    setup()
    fireEvent.change(screen.getByLabelText('Rule'), { target: { value: 'coerce_numeric' } })
    expect(await screen.findByText('boom')).toBeTruthy()
  })
})
