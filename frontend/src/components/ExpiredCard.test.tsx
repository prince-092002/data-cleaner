import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppStateProvider } from '@/state/AppState'
import { ExpiredCard } from './ExpiredCard'

afterEach(() => vi.unstubAllEnvs())
const setup = () =>
  render(
    <AppStateProvider>
      <ExpiredCard />
    </AppStateProvider>,
  )

describe('ExpiredCard', () => {
  it('says the result expired on the server', () => {
    setup()
    expect(screen.getByRole('alert')).toHaveTextContent('This result has expired. Please upload the file again.')
  })

  it('says the result is gone from this tab in browser mode', () => {
    vi.stubEnv('VITE_ENGINE', 'browser')
    setup()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'This result is no longer in this browser tab. Please choose the file again.',
    )
  })
})
