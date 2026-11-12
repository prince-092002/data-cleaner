import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  it('shows an error state', async () => {
    hoisted.fail = true
    setup()
    fireEvent.change(screen.getByLabelText('Rule'), { target: { value: 'coerce_numeric' } })
    expect(await screen.findByText('boom')).toBeTruthy()
  })
})
