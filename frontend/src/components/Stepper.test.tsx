import { render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { ProfileResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { Stepper } from './Stepper'

function Seed({ step, running }: { step: number; running: boolean }) {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1' } as UploadResponse })
    dispatch({ type: 'profile_loaded', profile: {} as ProfileResponse })
    if (running) dispatch({ type: 'job_started', jobId: 'j' })
    dispatch({ type: 'goto', step })
    setReady(true)
  }, [dispatch, step, running])
  return ready ? <Stepper /> : null
}
const setup = (step: number, running: boolean) =>
  render(
    <AppStateProvider>
      <Seed step={step} running={running} />
    </AppStateProvider>,
  )

describe('Stepper', () => {
  it('lets the user go back when no job runs', () => {
    setup(2, false)
    expect(screen.getByRole('button', { name: /Profile/ })).toBeEnabled()
  })

  it('disables other steps while a clean job runs', () => {
    setup(2, true)
    const profileBtn = screen.getByRole('button', { name: /Profile/ })
    expect(profileBtn).toBeDisabled()
    expect(profileBtn).toHaveAttribute('aria-disabled', 'true')
    expect(profileBtn).toHaveAttribute('title', 'A job is still running. Wait for it to finish.')
    expect(screen.getByRole('button', { name: /Processing/ })).toBeEnabled()
  })
})
