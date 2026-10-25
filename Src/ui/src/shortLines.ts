// 짧은 대사 묶어 보이기: 지금 줄 바로 뒤에 이어지는 짧은 대사들 (음향 · 암전 · 안내 줄은 건너뛰고 본다).

import type { Cue } from './cues'
import { SHORT_LINE_MAX_GROUPED, SHORT_LINE_SYLLABLES } from './settings'

const syllables = (text: string) => (text.match(/[가-힣]/g) ?? []).length

/** currentId 바로 뒤에 이어지는 짧은 대사들. 대사가 아니거나 길면 거기서 멈춘다 */
export function shortFollowers(cues: Cue[], currentId: number | null): Cue[] {
  const at = cues.findIndex((c) => c.id === currentId)
  if (at < 0) return []
  const out: Cue[] = []
  for (let i = at + 1; i < cues.length && out.length < SHORT_LINE_MAX_GROUPED; i++) {
    const cue = cues[i]
    if (cue.type === 'sound' || cue.type === 'blackout' || cue.type === 'notice') continue
    if (cue.type !== 'dialogue' || syllables(cue.text) > SHORT_LINE_SYLLABLES) break
    out.push(cue)
  }
  return out
}
