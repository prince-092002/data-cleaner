import { useEffect, useRef, useState } from 'react'
import { getResults } from '@/api/client'
import type {
  ChangeAction,
  ChangesPage,
  ChangeType,
  ColumnQuality,
  QualityScore,
  ResultsQuery,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAppState } from '@/state/AppState'

export const PAGE_SIZE = 50

const SCORE_ROWS: { key: keyof QualityScore; label: string; hint: string }[] = [
  { key: 'overall', label: 'Overall', hint: 'Combined score across all dimensions' },
  { key: 'completeness', label: 'Completeness', hint: 'Share of cells that are filled' },
  { key: 'validity', label: 'Validity', hint: 'Values that fit their column type' },
  { key: 'consistency', label: 'Consistency', hint: 'Same thing written the same way' },
  { key: 'uniqueness', label: 'Uniqueness', hint: 'Rows that are not duplicates' },
  { key: 'conformity', label: 'Conformity', hint: 'Values that follow expected formats' },
]
const CHANGE_TYPES: ChangeType[] = ['cell', 'row_removed', 'column_removed', 'header_renamed', 'column_added']
const SELECT_CLASS =
  'h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600'

const r = (n: number) => Math.round(n * 10) / 10
const fmtDelta = (d: number) => `${d > 0 ? '+' : ''}${r(d)}`

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-white p-4" data-testid="tile">
      <p className="text-sm text-slate-600">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </div>
  )
}

function Trunc({ value }: { value: string | null }) {
  if (value === null) return <span className="text-slate-500">(empty)</span>
  return (
    <span title={value} className="block max-w-[14rem] truncate">
      {value}
    </span>
  )
}

function ChangeLog({
  datasetId,
  initial,
  rules,
  columns,
}: {
  datasetId: string
  initial: ChangesPage
  rules: string[]
  columns: string[]
}) {
  const [page, setPage] = useState<ChangesPage>(initial)
  const [offset, setOffset] = useState(0)
  const [ruleId, setRuleId] = useState('')
  const [column, setColumn] = useState('')
  const [columnQ, setColumnQ] = useState('')   // the column text the server is asked about, 300 ms after typing stops
  const [action, setAction] = useState<ChangeAction | ''>('')
  const [changeType, setChangeType] = useState<ChangeType | ''>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const first = useRef(true)
  const pageSize = initial.limit > 0 ? initial.limit : PAGE_SIZE
  const reqId = useRef(0)

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    const id = ++reqId.current
    const q: ResultsQuery = { limit: pageSize, offset }
    if (ruleId) q.rule_id = ruleId
    if (columnQ) q.column = columnQ
    if (action) q.action = action
    if (changeType) q.change_type = changeType
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const res = await getResults(datasetId, q)
        if (id === reqId.current) setPage(res.changes)
      } catch (e) {
        if (id === reqId.current) setError(e instanceof Error ? e.message : 'Could not load changes.')
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    })()
  }, [datasetId, offset, pageSize, ruleId, columnQ, action, changeType])

  useEffect(() => {
    if (column === columnQ) return
    const t = setTimeout(() => {
      setColumnQ(column)
      setOffset(0)
    }, 300)
    return () => clearTimeout(t)
  }, [column, columnQ])

  const onFilter = (set: (v: string) => void) => (v: string) => {
    set(v)
    setOffset(0)
  }
  const from = page.total === 0 ? 0 : page.offset + 1
  const to = Math.min(page.offset + page.items.length, page.total)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Change log</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <Label htmlFor="f-rule">Rule</Label>
            <select id="f-rule" className={SELECT_CLASS} value={ruleId} onChange={(e) => onFilter(setRuleId)(e.target.value)}>
              <option value="">All rules</option>
              {rules.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-column">Column</Label>
            <Input
              id="f-column"
              list="f-column-list"
              value={column}
              onChange={(e) => setColumn(e.target.value)}
              placeholder="Any column"
            />
            <datalist id="f-column-list">
              {columns.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-action">Action</Label>
            <select
              id="f-action"
              className={SELECT_CLASS}
              value={action}
              onChange={(e) => onFilter((v) => setAction(v as ChangeAction | ''))(e.target.value)}
            >
              <option value="">All actions</option>
              <option value="auto">auto</option>
              <option value="approved">approved</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-type">Change type</Label>
            <select
              id="f-type"
              className={SELECT_CLASS}
              value={changeType}
              onChange={(e) => onFilter((v) => setChangeType(v as ChangeType | ''))(e.target.value)}
            >
              <option value="">All types</option>
              {CHANGE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-red-700">
            {error}
          </p>
        )}
        {loading && (
          <p role="status" className="text-sm text-slate-600">
            Loading changes...
          </p>
        )}

        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Row</TableHead>
                <TableHead>Column</TableHead>
                <TableHead>Rule</TableHead>
                <TableHead>Old value</TableHead>
                <TableHead>New value</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Type</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.items.map((c, i) => (
                <TableRow key={`${c.rule_id}-${c.row_id}-${c.column}-${i}`} data-testid="change-row">
                  <TableCell>{c.row_id ?? ''}</TableCell>
                  <TableCell>{c.column ?? ''}</TableCell>
                  <TableCell>{c.rule_id}</TableCell>
                  <TableCell>
                    <Trunc value={c.old_value} />
                  </TableCell>
                  <TableCell>
                    <Trunc value={c.new_value} />
                  </TableCell>
                  <TableCell>{c.action}</TableCell>
                  <TableCell>{c.change_type}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {page.items.length === 0 && !loading && !error && (
          <p className="text-slate-600">No changes match these filters.</p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-slate-700" aria-live="polite">
            Showing {from}-{to} of {page.total}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>
              Previous
            </Button>
            <Button variant="outline" disabled={loading || offset + pageSize >= page.total} onClick={() => setOffset(offset + pageSize)}>
              Next
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function qualityCell(q: ColumnQuality | null, missing: string) {
  return q ? String(r(q.score)) : missing
}

export function ResultsScreen() {
  const { state, dispatch } = useAppState()
  const { results, datasetId } = state

  if (!results || !datasetId) {
    return (
      <Card>
        <CardContent className="space-y-4 pt-6">
          <p>No results are available yet. Go back and apply your fixes first.</p>
          <Button onClick={() => dispatch({ type: 'goto', step: 2 })}>Back to suggested fixes</Button>
        </CardContent>
      </Card>
    )
  }

  const { before, after, summary } = results
  const delta = after.overall - before.overall

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Results</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-2xl font-semibold" data-testid="headline">
            Quality score: {r(before.overall)} {'->'} {r(after.overall)}{' '}
            <span className={delta >= 0 ? 'text-green-700' : 'text-red-700'}>({fmtDelta(delta)})</span>
          </p>
          <div className="overflow-x-auto">
            <Table className="min-w-[20rem]">
              <TableHeader>
                <TableRow>
                  <TableHead>Dimension</TableHead>
                  <TableHead>Before</TableHead>
                  <TableHead>After</TableHead>
                  <TableHead>Change</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {SCORE_ROWS.map(({ key, label, hint }) => {
                  const d = r(after[key] - before[key])
                  const word = d === 0 ? 'unchanged' : `${d > 0 ? 'up' : 'down'} ${Math.abs(d).toFixed(1)}`
                  const color = d > 0 ? 'text-green-700' : d < 0 ? 'text-red-700' : 'text-slate-700'
                  return (
                    <TableRow key={key} data-testid="dimension-row">
                      <TableCell className="whitespace-normal">
                        <span className="font-medium">{label}</span>
                        <span className="block text-xs font-normal text-slate-600">{hint}</span>
                      </TableCell>
                      <TableCell>{before[key].toFixed(1)}</TableCell>
                      <TableCell>{after[key].toFixed(1)}</TableCell>
                      <TableCell className={`font-medium ${color}`}>
                        <span aria-hidden="true">{d > 0 ? '+' : ''}{d.toFixed(1)}</span>
                        <span className="sr-only">{word}</span>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {results.warnings.length > 0 && (
        <div role="alert" className="rounded-lg border border-amber-400 bg-amber-50 p-4 text-amber-900">
          <p className="font-semibold">Warnings</p>
          <ul className="list-disc pl-5">
            {results.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Cells changed" value={String(summary.cells_changed)} />
        <Tile label="Rows" value={`${summary.rows_before} -> ${summary.rows_after} (${summary.rows_removed} removed)`} />
        <Tile label="Columns removed" value={String(summary.columns_removed)} />
        <Tile label="Columns added" value={String(summary.columns_added)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Changes by rule</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Changes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.by_rule.map((b) => (
                <TableRow key={`${b.rule_id}-${b.action}`}>
                  <TableCell>{b.rule_id}</TableCell>
                  <TableCell>{b.action}</TableCell>
                  <TableCell>{b.changes}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Score by column</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Column</TableHead>
                <TableHead>Before</TableHead>
                <TableHead>After</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {results.columns.map((c) => (
                <TableRow key={c.name} data-testid="column-row">
                  <TableCell>{c.name}</TableCell>
                  <TableCell>{qualityCell(c.before, 'new')}</TableCell>
                  <TableCell>{qualityCell(c.after, 'removed')}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <ChangeLog
        datasetId={datasetId}
        initial={results.changes}
        rules={[...new Set(summary.by_rule.map((b) => b.rule_id))]}
        columns={results.columns.map((c) => c.name)}
      />

      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="outline" onClick={() => dispatch({ type: 'goto', step: 2 })}>
          Back to suggested fixes
        </Button>
        <Button onClick={() => dispatch({ type: 'goto', step: 5 })}>Continue to downloads</Button>
      </div>
    </div>
  )
}
