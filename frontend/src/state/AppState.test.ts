import { describe, expect, it } from 'vitest'
import type { UploadResponse } from '@/api/types'
import { initialState, reducer } from './AppState'

const upload: UploadResponse = {
  dataset_id: 'd1',
  filename: 'a.csv',
  file_type: 'csv',
  size_bytes: 10,
  expires_at: '2026-11-12T00:00:00Z',
  sheets: [],
}

describe('app reducer', () => {
  it('moves to Profile after upload', () => {
    const s = reducer(initialState, { type: 'uploaded', upload })
    expect(s.step).toBe(1)
    expect(s.datasetId).toBe('d1')
  })

  it('clamps step navigation', () => {
    expect(reducer(initialState, { type: 'goto', step: -3 }).step).toBe(0)
    expect(reducer(initialState, { type: 'goto', step: 99 }).step).toBe(5)
  })

  it('job_started sets jobRunning and job_finished clears it', () => {
    const s = reducer(initialState, { type: 'job_started', jobId: 'j1' })
    expect(s.jobRunning).toBe(true)
    expect(reducer(s, { type: 'job_finished' }).jobRunning).toBe(false)
    expect(reducer(s, { type: 'reset' }).jobRunning).toBe(false)
  })

  it('resets', () => {
    const s = reducer(reducer(initialState, { type: 'uploaded', upload }), { type: 'reset' })
    expect(s).toEqual(initialState)
  })
})
