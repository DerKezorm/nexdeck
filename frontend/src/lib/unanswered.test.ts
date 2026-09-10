/**
 * Which blanks still need an answer, and what a pick list starts on.
 *
 * ⚠️ The second question is the dangerous one. Starting a list on its first
 * entry turns "nobody chose" into "somebody chose the first folder", and a
 * title lands there without anyone having decided it.
 */
import { describe, expect, it } from 'vitest'

import type { Action, Ask } from './types'
import { startingValue, unanswered } from './unanswered'

const FOLDERS: Ask = {
  name: 'root_folder_path', label: 'Target folder', kind: 'choice',
  options: [{ value: '/media/films', label: 'Films' }, { value: '/media/kids', label: 'Kids' }],
}
const PROFILE: Ask = { name: 'quality_profile_id', label: 'Quality profile', kind: 'choice', options: [{ value: '4', label: 'HD-1080p' }] }
const ADDRESS: Ask = { name: 'url', label: 'Video address', kind: 'url' }

const action = (params: Record<string, unknown>, asks: Ask[]): Action => ({ id: 'approve', label: 'Approve', params, asks })

describe('unanswered', () => {
  it('lists every blank nobody has filled in', () => {
    expect(unanswered(action({ id: 12 }, [FOLDERS, PROFILE])).map((one) => one.name)).toEqual(['root_folder_path', 'quality_profile_id'])
  })

  it('leaves out a blank the card already filled, which is how a field on a card goes straight through', () => {
    expect(unanswered(action({ url: 'https://videos.example.com/x' }, [ADDRESS]))).toEqual([])
  })

  it('counts blanks and nothing but blanks as unanswered', () => {
    expect(unanswered(action({ root_folder_path: '   ' }, [FOLDERS])).length).toBe(1)
    expect(unanswered(action({ root_folder_path: null }, [FOLDERS])).length).toBe(1)
    expect(unanswered(action({ quality_profile_id: 0 }, [PROFILE])).length).toBe(0)
  })

  it('has nothing to ask for an action without blanks', () => {
    expect(unanswered({ id: 'restart', label: 'Restart' })).toEqual([])
  })
})

describe('startingValue', () => {
  it('starts empty when there is more than one thing to pick', () => {
    expect(startingValue(FOLDERS)).toBe('')
  })

  it('starts on the only entry when there is exactly one', () => {
    expect(startingValue(PROFILE)).toBe('4')
  })

  it('starts a text field empty', () => {
    expect(startingValue(ADDRESS)).toBe('')
  })
})
