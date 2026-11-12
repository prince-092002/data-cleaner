import { useState } from 'react'
import { startClean, ApiError } from '@/api/client'
import type { Decisions, EditedProposal, LeftAlone, Proposal } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useAppState } from '@/state/AppState'

export type Status = 'approved' | 'rejected' | 'undecided'
type Params = Record<string, unknown>

type Mapping = Record<string, string>

/** Tier 1 category merges (case, accents, spaces): shown in their own section with Undo. */
const isAutoMerge = (p: Proposal) =>
  p.rule_id === 'standardize_categories' && p.params.tier === 1

const STATUS_STYLE: Record<Status, string> = {
  approved: 'bg-green-100 text-green-900',
  rejected: 'bg-red-100 text-red-900',
  undecided: 'bg-slate-100 text-slate-800',
}

const STATUS_LABEL: Record<Status, string> = {
  approved: 'Approved',
  rejected: 'Rejected',
  undecided: 'Undecided',
}

/** Per the build_plan rules: only suggest-mode proposals need an explicit approval to run. */
export function statusLabel(status: Status, mode: Proposal['mode']): string {
  if (status === 'undecided') return mode === 'suggest' ? 'Undecided (will not run)' : 'Runs unless rejected'
  return STATUS_LABEL[status]
}

/**
 * "Safe" rule for "Approve all safe fixes": not destructive, not flag-only, not a category
 * merge or name casing (judgment calls) and not an ambiguous-date parse (needs an explicit
 * order choice).
 */
export function isSafe(p: Proposal, ambiguous = false): boolean {
  return (
    !p.is_destructive &&
    p.mode !== 'flag' &&
    p.rule_id !== 'standardize_categories' &&
    p.params.name_case !== true &&
    !(p.rule_id === 'parse_dates' && ambiguous)
  )
}

export function initialStatuses(proposals: Proposal[], d: Decisions): Record<string, Status> {
  const hasSaved = d.approved.length + d.rejected.length > 0
  const out: Record<string, Status> = {}
  for (const p of proposals) {
    if (d.approved.includes(p.id)) out[p.id] = 'approved'
    else if (d.rejected.includes(p.id)) out[p.id] = 'rejected'
    else out[p.id] = !hasSaved && p.mode === 'auto' ? 'approved' : 'undecided'
  }
  return out
}

export function buildDecisions(
  proposals: Proposal[],
  statuses: Record<string, Status>,
  edits: Record<string, Params>,
): Decisions {
  const approved = proposals.filter((p) => statuses[p.id] === 'approved').map((p) => p.id)
  const rejected = proposals.filter((p) => statuses[p.id] === 'rejected').map((p) => p.id)
  const edited: EditedProposal[] = approved
    .filter((id) => edits[id])
    .map((id) => ({ id, params: edits[id] }))
  return { approved, rejected, edited }
}

const show = (v: string | null) => (v === null || v === '' ? '(empty)' : v)

function Samples({ p }: { p: Proposal }) {
  if (p.samples.length === 0) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Sample changes for {p.title}</caption>
        <thead>
          <tr className="text-slate-600">
            <th scope="col" className="py-1 pr-3 font-medium">Before</th>
            <th scope="col" className="py-1 font-medium">After</th>
          </tr>
        </thead>
        <tbody>
          {p.samples.slice(0, 5).map((s, i) => (
            <tr key={`${s.row_id ?? "x"}-${i}`} className="border-t">
              <td className="py-1 pr-3 font-mono break-all">{show(s.before)}</td>
              <td className="py-1 font-mono break-all">{show(s.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MergeList({ mapping, reasons }: { mapping: Mapping; reasons: Mapping }) {
  const entries = Object.entries(mapping)
  if (entries.length === 0) return null
  return (
    <ul className="space-y-2" aria-label="Values to merge">
      {entries.map(([from, to]) => (
        <li key={from} className="rounded-md border p-2">
          <p className="font-mono break-all">
            {from} <span aria-hidden="true">&rarr;</span>
            <span className="sr-only">becomes</span> {to}
          </p>
          {reasons[from] && <p className="mt-1 text-xs text-slate-700">{reasons[from]}</p>}
        </li>
      ))}
    </ul>
  )
}

function LeftAloneList({ items }: { items: LeftAlone[] }) {
  if (items.length === 0) return null
  return (
    <details className="rounded-md border bg-slate-50 p-3 text-sm" open={items.length <= 5}>
      <summary className="cursor-pointer font-medium">Left alone ({items.length})</summary>
      <p className="mt-1 text-xs text-slate-700">
        Values the cleaner saw in this column but did not change.
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((x) => (
          <li key={x.value}>
            <span className="font-mono break-all">{x.value}</span>{' '}
            <span className="text-xs text-slate-600">
              ({x.count.toLocaleString()} {x.count === 1 ? 'row' : 'rows'})
            </span>
            <p className="text-xs text-slate-700">{x.reason}</p>
          </li>
        ))}
      </ul>
    </details>
  )
}

function AutoMerges({
  items,
  isUndone,
  onToggle,
}: {
  items: Proposal[]
  isUndone: (p: Proposal, from: string) => boolean
  onToggle: (p: Proposal, from: string) => void
}) {
  return (
    <section
      aria-labelledby="auto-merges-heading"
      className="space-y-3 rounded-lg border bg-white p-4"
    >
      <div>
        <h3 id="auto-merges-heading" className="text-lg font-semibold">
          Automatic merges
        </h3>
        <p className="mt-1 text-sm text-slate-700">
          These spellings differ only by capital letters, accents or spaces, so they are merged
          without asking. Undo any you want to keep as written.
        </p>
      </div>
      {items.map((p) => (
        <div key={p.id}>
          <h4 className="text-sm font-semibold break-all">Column {p.column}</h4>
          <ul className="mt-1 divide-y">
            {Object.entries(p.params.mapping as Mapping).map(([from, to]) => {
              const undone = isUndone(p, from)
              return (
                <li key={from} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                  <span
                    className={`font-mono text-sm break-all ${undone ? 'text-slate-500 line-through' : ''}`}
                  >
                    {from} <span aria-hidden="true">&rarr;</span>
                    <span className="sr-only">becomes</span> {to}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="min-h-11 min-w-20"
                    aria-label={`${undone ? 'Redo' : 'Undo'} merge of ${from} into ${to}`}
                    onClick={() => onToggle(p, from)}
                  >
                    {undone ? 'Redo' : 'Undo'}
                  </Button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </section>
  )
}

function MappingEditor({
  mapping,
  onChange,
}: {
  mapping: Record<string, string>
  onChange: (m: Record<string, string>) => void
}) {
  return (
    <div className="space-y-1">
      <p className="text-sm font-medium">Value mapping (from, to)</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-600">
            <th scope="col" className="font-medium">From</th>
            <th scope="col" className="font-medium">To</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(mapping).map(([from, to]) => (
            <tr key={from}>
              <td className="py-1 pr-2 font-mono break-all">{from}</td>
              <td className="py-1">
                <Input
                  aria-label={`Replace ${from} with`}
                  value={to}
                  onChange={(e) => onChange({ ...mapping, [from]: e.target.value })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EditDialog({
  proposal,
  params,
  onClose,
  onSave,
}: {
  proposal: Proposal
  params: Params
  onClose: () => void
  onSave: (params: Params) => void
}) {
  const [draft, setDraft] = useState<Params>(() => ({ ...params }))
  const set = (k: string, v: unknown) => setDraft((d) => ({ ...d, [k]: v }))
  const dayOptions: [boolean, string][] = [
    [true, 'Day first (31/12/2024)'],
    [false, 'Month first (12/31/2024)'],
  ]
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit: {proposal.title}</DialogTitle>
          <DialogDescription>Saving approves this fix with your changes.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {proposal.editable_params.includes('dayfirst') && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Date order</legend>
              {dayOptions.map(([val, label]) => (
                <label key={String(val)} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="dayfirst"
                    checked={draft.dayfirst === val}
                    onChange={() => set('dayfirst', val)}
                  />
                  {label}
                </label>
              ))}
            </fieldset>
          )}
          {proposal.editable_params.includes('mapping') && (
            <MappingEditor
              mapping={(draft.mapping as Record<string, string>) ?? {}}
              onChange={(m) => set('mapping', m)}
            />
          )}
          {proposal.editable_params.includes('k') && (
            <div className="space-y-1">
              <label htmlFor="param-k" className="text-sm font-medium">
                Outlier sensitivity (k, lower flags more values)
              </label>
              <Input
                id="param-k"
                type="number"
                step="0.1"
                min="0"
                value={String(draft.k ?? '')}
                onChange={(e) => set('k', e.target.value === '' ? '' : Number(e.target.value))}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onSave(draft)}>Save and approve</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProposalCard({
  p,
  status,
  params,
  ambiguous,
  choiceMade,
  onStatus,
  onEdit,
  onChooseDayfirst,
}: {
  p: Proposal
  status: Status
  params: Params
  ambiguous: boolean
  choiceMade: boolean
  onStatus: (s: Status) => void
  onEdit: () => void
  onChooseDayfirst: (dayfirst: boolean) => void
}) {
  const dayfirst = params.dayfirst === true
  const needsChoice = p.rule_id === 'parse_dates' && ambiguous && !choiceMade
  return (
    <Card data-testid="proposal-card">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-start justify-between gap-2">
          <h4 className="text-base font-semibold">
            {p.column && p.title.endsWith(`: ${p.column}`)
              ? p.title.slice(0, -(p.column.length + 2))
              : p.title}
          </h4>
          <span
            data-testid="status"
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}
          >
            {statusLabel(status, p.mode)}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>{p.description}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">
            {p.severity[0].toUpperCase() + p.severity.slice(1)} severity
          </Badge>
          <Badge variant="secondary">{p.rows_affected.toLocaleString()} rows affected</Badge>
          <Badge variant="secondary">Mode: {p.mode}</Badge>
          {p.is_destructive && <Badge variant="destructive">Destructive</Badge>}
          {p.confidence !== null && (
            <Badge variant="outline">Confidence {Math.round(p.confidence * 100)}%</Badge>
          )}
        </div>
        {p.rule_id === 'parse_dates' && 'dayfirst' in params && (
          <div className="rounded-md border border-blue-200 bg-blue-50 p-3">
            {ambiguous && (
              <p className="mb-2 text-slate-900">
                These dates could be read two ways (for example 03/04/2024 is either 3 April or 4
                March). Please check the samples and pick the order that is right.
              </p>
            )}
            <p className="font-medium">
              Reading dates as: {dayfirst ? 'Day first (31/12/2024)' : 'Month first (12/31/2024)'}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {([true, false] as const).map((val) => (
                <Button
                  key={String(val)}
                  variant={dayfirst === val ? 'default' : 'outline'}
                  size="sm"
                  aria-pressed={dayfirst === val}
                  onClick={() => onChooseDayfirst(val)}
                >
                  {val ? 'Day first' : 'Month first'}
                </Button>
              ))}
            </div>
            <p className="mt-1 text-xs text-slate-600">
              Choosing an order approves this fix. The samples below show the original suggestion.
            </p>
          </div>
        )}
        {p.rule_id === 'standardize_categories' ? (
          <MergeList
            mapping={(params.mapping as Mapping) ?? {}}
            reasons={(p.params.reasons as Mapping) ?? {}}
          />
        ) : (
          <Samples p={p} />
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant={status === 'approved' ? 'default' : 'outline'}
            aria-pressed={status === 'approved'}
            disabled={needsChoice}
            onClick={() => onStatus(status === 'approved' ? 'undecided' : 'approved')}
          >
            Approve
          </Button>
          {needsChoice && (
            <span className="self-center text-xs text-slate-700">
              Choose day-first or month-first first
            </span>
          )}
          <Button
            variant={status === 'rejected' ? 'default' : 'outline'}
            aria-pressed={status === 'rejected'}
            onClick={() => onStatus(status === 'rejected' ? 'undecided' : 'rejected')}
          >
            Reject
          </Button>
          {p.editable_params.length > 0 && (
            <Button variant="outline" onClick={onEdit}>
              Edit
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function FixesScreen() {
  const { state, dispatch } = useAppState()
  const proposals = state.profile?.proposals ?? []
  const [statuses, setStatuses] = useState<Record<string, Status>>(() =>
    initialStatuses(proposals, state.decisions),
  )
  const [edits, setEdits] = useState<Record<string, Params>>(() =>
    Object.fromEntries(state.decisions.edited.map((e) => [e.id, e.params])),
  )
  const [chosen, setChosen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(state.decisions.edited.map((e) => [e.id, true])),
  )
  const [editing, setEditing] = useState<Proposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const paramsOf = (p: Proposal): Params => edits[p.id] ?? p.params
  const isAmbiguous = (p: Proposal) =>
    !!state.profile?.columns.some(
      (c) => c.name === p.column && c.issues.some((i) => i.code === 'ambiguous_dates'),
    )
  const setStatus = (id: string, s: Status) => setStatuses((m) => ({ ...m, [id]: s }))
  const saveEdit = (id: string, params: Params) => {
    setEdits((m) => ({ ...m, [id]: params }))
    setChosen((m) => ({ ...m, [id]: true }))
    setStatus(id, 'approved')
  }
  const approveAllSafe = () =>
    setStatuses((m) => {
      const next = { ...m }
      for (const p of proposals) if (isSafe(p, isAmbiguous(p))) next[p.id] = 'approved'
      return next
    })

  const count = (s: Status) => proposals.filter((p) => statuses[p.id] === s).length

  // Automatic merges: undoing removes one value from the mapping; undoing all rejects the fix.
  const currentMapping = (p: Proposal): Mapping =>
    statuses[p.id] === 'rejected' ? {} : ((paramsOf(p).mapping as Mapping) ?? {})
  const isUndone = (p: Proposal, from: string) => !(from in currentMapping(p))
  const toggleMerge = (p: Proposal, from: string) => {
    const original = p.params.mapping as Mapping
    const next = { ...currentMapping(p) }
    if (from in next) delete next[from]
    else next[from] = original[from]
    const size = Object.keys(next).length
    const full = size === Object.keys(original).length
    setEdits((m) => {
      const rest = { ...m }
      delete rest[p.id]
      return size === 0 || full ? rest : { ...rest, [p.id]: { ...p.params, mapping: next } }
    })
    setStatus(p.id, size === 0 ? 'rejected' : 'approved')
  }

  const autoMerges = proposals.filter(isAutoMerge)
  const others = proposals.filter((p) => !isAutoMerge(p))
  const tableFixes = others.filter((p) => p.column === null)
  const columns = [
    ...new Set(others.filter((p) => p.column !== null).map((p) => p.column as string)),
  ]
  const plural = (n: number) => `${n} ${n === 1 ? 'fix' : 'fixes'}`
  const renderCard = (p: Proposal) => (
    <ProposalCard
      key={p.id}
      p={p}
      status={statuses[p.id]}
      params={paramsOf(p)}
      ambiguous={isAmbiguous(p)}
      onStatus={(s) => setStatus(p.id, s)}
      onEdit={() => setEditing(p)}
      choiceMade={!!chosen[p.id]}
      onChooseDayfirst={(dayfirst) => saveEdit(p.id, { ...paramsOf(p), dayfirst })}
    />
  )

  async function start() {
    if (!state.datasetId) return
    const decisions = buildDecisions(proposals, statuses, edits)
    setBusy(true)
    setError(null)
    dispatch({ type: 'set_decisions', decisions })
    try {
      const { job_id } = await startClean(state.datasetId, decisions)
      dispatch({ type: 'job_started', jobId: job_id })
      dispatch({ type: 'goto', step: 3 })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="fixes-heading" className="space-y-6">
      <div>
        <h2 id="fixes-heading" className="text-2xl font-semibold">
          Suggested fixes
        </h2>
        <p className="mt-1 text-sm text-slate-700">
          Review each fix. Rejected fixes are never applied. Suggested fixes run only if you approve
          them; automatic and flag-only fixes run unless you reject them. Your original file is
          never modified.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border bg-white p-4 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap gap-4 text-sm" aria-live="polite">
          <span>
            Approved: <strong>{count('approved')}</strong>
          </span>
          <span>
            Rejected: <strong>{count('rejected')}</strong>
          </span>
          <span>
            Undecided: <strong>{count('undecided')}</strong>
          </span>
        </div>
        <div>
          <Button variant="outline" onClick={approveAllSafe} aria-describedby="safe-desc">
            Approve all safe fixes
          </Button>
          <p id="safe-desc" className="mt-1 text-xs text-slate-600">
            Excludes category merges, name capitals, ambiguous dates, destructive and flag-only
            fixes, which need an explicit choice.
          </p>
        </div>
      </div>

      {proposals.length === 0 && <p>No fixes were suggested for this file.</p>}

      {autoMerges.length > 0 && (
        <AutoMerges items={autoMerges} isUndone={isUndone} onToggle={toggleMerge} />
      )}

      {tableFixes.length > 0 && (
        <section aria-labelledby="table-fixes" className="space-y-3">
          <h3 id="table-fixes" className="text-lg font-semibold">
            Whole table ({plural(tableFixes.length)})
          </h3>
          <div className="grid gap-4 md:grid-cols-2">{tableFixes.map(renderCard)}</div>
        </section>
      )}

      {columns.map((name, i) => {
        const group = others.filter((p) => p.column === name)
        const left = group.flatMap((p) => p.left_alone ?? [])
        return (
          <section key={name} aria-labelledby={`col-${i}`} className="space-y-3">
            <h3 id={`col-${i}`} className="text-lg font-semibold break-all">
              Column {name}{' '}
              <span className="text-base font-normal text-slate-600">({plural(group.length)})</span>
            </h3>
            <div className="grid gap-4 md:grid-cols-2">{group.map(renderCard)}</div>
            <LeftAloneList items={left} />
          </section>
        )
      })}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900"
        >
          {error}
        </p>
      )}

      <div className="flex justify-between gap-3">
        <Button variant="outline" onClick={() => dispatch({ type: 'goto', step: 1 })}>
          Back
        </Button>
        <div className="flex flex-col items-end gap-1">
          <Button onClick={start} disabled={busy || state.jobRunning}>
            {busy ? 'Starting…' : 'Start cleaning'}
          </Button>
          {state.jobRunning && (
            <p className="text-sm text-slate-700">A job is still running. Wait for it to finish.</p>
          )}
        </div>
      </div>

      {editing && (
        <EditDialog
          proposal={editing}
          params={paramsOf(editing)}
          onClose={() => setEditing(null)}
          onSave={(params) => {
            saveEdit(editing.id, params)
            setEditing(null)
          }}
        />
      )}
    </section>
  )
}
