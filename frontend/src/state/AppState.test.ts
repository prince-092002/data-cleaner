import { describe, expect, it } from 'vitest'
import type { UploadResponse } from '@/api/types'
import { initFromUrl, initialState, reducer } from './AppState'

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
  it('restores a running clean job from the URL', () => {
    const s = initFromUrl('?d=d1&j=j9&s=processing')
    expect(s).toMatchObject({ step: 3, datasetId: 'd1', jobId: 'j9', jobRunning: true })
  })

  it('restores a running profile job, and later screens without a running job', () => {
    expect(initFromUrl('?d=d1&j=j1&s=profile').jobRunning).toBe(true)
    expect(initFromUrl('?d=d1&j=j1&s=results')).toMatchObject({ step: 4, jobRunning: false })
  })

  it('falls back to Suggested fixes when Processing has no job id', () => {
    expect(initFromUrl('?d=d1&s=processing').step).toBe(2)
  })

  it('starts fresh without usable URL ids', () => {
    expect(initFromUrl('')).toEqual(initialState)
  })
})
