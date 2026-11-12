import { cn } from '@/lib/utils'
import { STEPS, useAppState } from '@/state/AppState'

const PROCESSING = 3

export function Stepper() {
  const { state, dispatch } = useAppState()
  const current = state.step
  // The running job's own screen: profile job -> Profile (1), clean job -> Processing (3).
  const jobStep = state.profile ? PROCESSING : 1
  return (
    <nav aria-label="Progress">
      <p className="text-sm font-medium text-slate-700 md:hidden">
        Step {current + 1} of {STEPS.length}: {STEPS[current]}
      </p>
      <ol className="hidden md:flex md:items-center md:gap-2">
        {STEPS.map((label, i) => {
          const isCurrent = i === current
          const done = i < current
          const locked = state.jobRunning && i !== jobStep && i !== current && (done || i === PROCESSING)
          const clickable = state.jobRunning
            ? i === jobStep && !isCurrent
            : done && i !== PROCESSING
          const body = (
            <>
              <span
                className={cn(
                  'flex size-7 items-center justify-center rounded-full border text-sm font-semibold',
                  isCurrent && 'border-indigo-700 bg-indigo-700 text-white',
                  done && 'border-indigo-700 bg-indigo-50 text-indigo-800',
                  !isCurrent && !done && 'border-slate-400 bg-white text-slate-700',
                )}
                aria-hidden="true"
              >
                {done ? '✓' : i + 1}
              </span>
              <span className={cn('text-sm', isCurrent ? 'font-semibold text-slate-900' : 'text-slate-700')}>
                {label}
              </span>
            </>
          )
          return (
            <li
              key={label}
              className="flex items-center gap-2"
              aria-current={isCurrent ? 'step' : undefined}
            >
              {clickable ? (
                <button
                  type="button"
                  onClick={() => dispatch({ type: 'goto', step: i })}
                  className="flex items-center gap-2 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700"
                >
                  {body}
                </button>
              ) : locked ? (
                <button
                  type="button"
                  disabled
                  aria-disabled="true"
                  title="A job is still running. Wait for it to finish."
                  className="flex cursor-not-allowed items-center gap-2 rounded-md opacity-60"
                >
                  {body}
                </button>
              ) : (
                <span className="flex items-center gap-2">{body}</span>
              )}
              {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-slate-300" aria-hidden="true" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
