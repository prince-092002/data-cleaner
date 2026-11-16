import { useState } from 'react'
import { getProfile } from '@/api/client'
import type { ColumnProfile, IssueCode, ProfileResponse, QualityScore, SourceInfo } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { FocusedAlert } from '@/components/FocusedAlert'
import { ExpiredCard } from '@/components/ExpiredCard'
import { friendlyJobError, isNotFound } from '@/lib/jobErrors'
import { useJobPolling } from '@/lib/useJobPolling'
import { useAppState } from '@/state/AppState'

const ISSUE_LABELS: Record<IssueCode, string> = {
  missing_values: 'Missing values',
  null_tokens: 'Placeholder nulls',
  whitespace: 'Extra spaces',
  hidden_characters: 'Hidden characters',
  encoding_damage: 'Garbled text',
  mixed_types: 'Mixed types',
  numeric_as_text: 'Numbers stored as text',
  mixed_date_formats: 'Mixed date formats',
  ambiguous_dates: 'Ambiguous dates',
  inconsistent_booleans: 'Inconsistent yes/no',
  inconsistent_categories: 'Inconsistent categories',
  outliers: 'Outliers',
  duplicate_keys: 'Duplicate keys',
  messy_header: 'Messy header',
  empty_column: 'Empty column',
}

const DIMENSIONS: (keyof Omit<QualityScore, 'overall'>)[] = [
  'completeness',
  'validity',
  'consistency',
  'uniqueness',
  'conformity',
]

function ScoreBar({ label, value }: { label: string; value: number }) {
  const v = Math.round(value)
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span className="capitalize">{label}</span>
        <span className="font-medium">{v}</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={v}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-1 h-2 w-full rounded-full bg-slate-200"
      >
        <div className="h-2 rounded-full bg-blue-600" style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
      </div>
    </div>
  )
}

function ColumnCard({ col }: { col: ColumnProfile }) {
  return (
    <Card data-testid="column-card">
      <CardHeader>
        <CardTitle className="flex items-start justify-between gap-2">
          <h3 className="break-all text-base font-semibold">{col.name}</h3>
          <Badge variant="secondary">{col.inferred_type}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-2 gap-2">
          <div>
            <dt className="text-slate-600">Missing</dt>
            <dd className="font-medium">{Math.round(col.null_pct * 10) / 10}%</dd>
          </div>
          <div>
            <dt className="text-slate-600">Unique values</dt>
            <dd className="font-medium">{col.distinct_count}</dd>
          </div>
        </dl>
        <div>
          <p className="text-slate-600">Sample values</p>
          {col.samples.length ? (
            <p className="break-words">{col.samples.slice(0, 5).join(', ')}</p>
          ) : (
            <p className="text-slate-500">None</p>
          )}
        </div>
        {col.issues.length > 0 && (
          <ul className="flex flex-wrap gap-1" aria-label={`Issues in ${col.name}`}>
            {col.issues.map((i) => (
              <li key={i.code}>
                <Badge variant="outline" title={i.code}>
                  {ISSUE_LABELS[i.code] ?? i.code}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

export function ProfileScreen() {
  const { state, dispatch } = useAppState()
  const { profile, jobId, datasetId } = state
  const [pct, setPct] = useState(0)
  const [step, setStep] = useState('Starting')
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [queued, setQueued] = useState(true)

  useJobPolling(
    profile || !datasetId ? null : jobId,
    async (job) => {
      setQueued(job.status === 'queued')
      setPct(job.progress_pct)
      setStep(job.current_step)
      if (job.status === 'failed') {
        dispatch({ type: 'job_finished' })
        setError(friendlyJobError(job.error?.code, job.error?.message, 'Profiling failed.'))
        setExpired(job.error?.code === 'expired')
      } else if (job.status === 'done') {
        dispatch({ type: 'job_finished' })
        const p = await getProfile(datasetId!)
        dispatch({ type: 'profile_loaded', profile: p })
      }
    },
    (e) => {
      dispatch({ type: 'job_finished' })
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      setExpired(isNotFound(e))
    },
  )

  if (error && expired) return <ExpiredCard />

  if (error) {
    return (
      <Card>
        <CardContent className="space-y-4 pt-6">
          <FocusedAlert className="text-red-700">{error}</FocusedAlert>
          <Button onClick={() => dispatch({ type: 'reset' })}>Back to upload</Button>
        </CardContent>
      </Card>
    )
  }

  if (!profile) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Profiling your file</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Progress value={pct} aria-label="Profiling progress" />
          <p aria-live="polite" className="text-sm text-slate-700">
            {queued ? 'Waiting to start. Your file is in line.' : `${step} (${Math.round(pct)}%)`}
          </p>
        </CardContent>
      </Card>
    )
  }

  return <ProfileView profile={profile} />
}

const DELIMITER_NAMES: Record<string, string> = { ',': 'comma', ';': 'semicolon', '\t': 'tab', '|': 'pipe' }

function FileFacts({ source }: { source: SourceInfo }) {
  if (source.file_type === 'xlsx') {
    return <p className="mt-3 text-sm text-slate-600">Excel file</p>
  }
  return (
    <div className="mt-3 text-sm" data-testid="file-facts">
      {source.encoding && <p>Encoding: {source.encoding}</p>}
      {source.delimiter && <p>Delimiter: {DELIMITER_NAMES[source.delimiter] ?? source.delimiter}</p>}
      {source.encoding?.toLowerCase() === 'windows-1252' && (
        <p className="mt-1 text-xs text-slate-600">
          Latin-script files are read as Windows-1252. If accented letters look wrong (for example Polish or Czech
          text), the file may use a different encoding.
        </p>
      )}
    </div>
  )
}

function ProfileView({ profile }: { profile: ProfileResponse }) {
  const { dispatch } = useAppState()
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-xl font-semibold">Data quality</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-2">
          <div>
            <p className="text-sm text-slate-600">Overall quality score</p>
            <p className="text-6xl font-bold" data-testid="overall-score">
              {Math.round(profile.quality.overall)}
              <span className="text-2xl font-normal text-slate-500">/100</span>
            </p>
            <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
              <div>
                <dt className="text-slate-600">File</dt>
                <dd className="break-all font-medium">{profile.source.filename}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Rows</dt>
                <dd className="font-medium">{profile.row_count.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Columns</dt>
                <dd className="font-medium">{profile.column_count}</dd>
              </div>
            </dl>
            <FileFacts source={profile.source} />
          </div>
          <div className="space-y-3">
            {DIMENSIONS.map((d) => (
              <ScoreBar key={d} label={d} value={profile.quality[d]} />
            ))}
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="cols-h">
        <h2 id="cols-h" className="mb-3 text-xl font-semibold">
          Columns
        </h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {profile.columns.map((c) => (
            <ColumnCard key={`${c.position}-${c.name}`} col={c} />
          ))}
        </div>
      </section>

      <div className="flex gap-3">
        <Button variant="outline" onClick={() => dispatch({ type: 'goto', step: 0 })}>
          Back
        </Button>
        <Button onClick={() => dispatch({ type: 'goto', step: 2 })}>Continue to suggested fixes</Button>
      </div>
    </div>
  )
}
