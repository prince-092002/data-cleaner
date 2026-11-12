import { render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { DownloadsScreen } from './DownloadsScreen'

function Seed() {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1', expires_at: '2030-01-02T03:04:05Z' } as UploadResponse })
    setReady(true)
  }, [dispatch])
  return ready ? <DownloadsScreen /> : null
}

describe('DownloadsScreen', () => {
  it('renders five cards with correct hrefs', () => {
    render(
      <AppStateProvider>
        <Seed />
      </AppStateProvider>,
    )
    expect(screen.getAllByTestId('download-card')).toHaveLength(5)
    for (const n of ['clean.csv', 'clean.xlsx', 'report.html', 'recipe.yaml', 'changelog.csv']) {
      const a = screen.getByRole('link', { name: `Download ${n}` })
      expect(a.getAttribute('href')).toBe(`/api/datasets/d1/downloads/${n}`)
      expect(a.hasAttribute('download')).toBe(true)
    }
    const open = screen.getByRole('link', { name: 'Open in new tab' })
    expect(open.getAttribute('target')).toBe('_blank')
    expect(open.getAttribute('rel')).toBe('noopener')
    expect(screen.getByText(/24 hours after upload \(expires/)).toBeTruthy()
  })
})
