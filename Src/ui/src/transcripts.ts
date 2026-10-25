/**
 * 겹쳐 보낸 인식 조각을 이어 붙인다: 앞 글자 끝과 뒤 글자 앞이 같은 말이면 한 번만.
 *
 * 엔진은 3초 조각을 1.5초마다 보내서 앞 조각 끝과 뒤 조각 앞이 같은 소리다. 그런데 같은 소리도 조각마다 조금
 * 다르게 받아 적고(문장부호, 받침, 단어 한두 개), 뒤 조각이 앞 조각 끝보다 한두 단어 앞에서 시작하기도 한다.
 * 단어가 글자 그대로 같을 때만 겹친다고 보면 "…없애려고 했는데 그 딜레이를 좀 없애려고 했는데." 처럼
 * 같은 말이 두 번 들어가므로, 문장부호를 뺀 글자가 충분히 비슷하면(OVERLAP_SIMILAR) 겹친 것으로 본다.
 */

/** 뒤 조각이 앞 조각 끝보다 이만큼(단어) 앞에서 시작해도 겹친 곳을 찾는다 */
const MAX_SHIFT = 2
/** 겹친 부분 글자가 이만큼 비슷하면 같은 말로 본다 (0~1, 두 단어 이상일 때. 한 단어는 같아야 함) */
const OVERLAP_SIMILAR = 0.8
/** 뒤 조각을 밀어서 맞출 때는 겹친 글자가 이만큼 이상이어야 한다 ("거 아니야" 같은 흔한 말끝으로 잘못 잇지 않게) */
const MIN_SHIFTED_CHARS = 5
/** 한 단어만 겹칠 때: 조각 경계에서 앞이 잘린 단어("미끄러운데요" → "부러운데요")도 이만큼 비슷하고 4글자 넘으면 같은 말 */
const ONE_WORD_SIMILAR = 0.65

export function mergeTranscripts(parts: string[]): string {
  let words: string[] = []
  for (const part of parts) {
    const next = part.split(/\s+/).filter(Boolean)
    const end = overlapEnd(words, next)
    // 앞 조각 끝에서 잘린 단어("움직이")는 뒤 조각의 온전한 단어("움직이세요.")로 바꾼다
    if (end > 0 && words.length > 0) {
      const last = key([words[words.length - 1]])
      const full = key([next[end - 1]])
      if (last && full.length > last.length && full.startsWith(last)) words = [...words.slice(0, -1), next[end - 1]]
    }
    words = [...words, ...next.slice(end)]
  }
  return words.join(' ')
}

/** next 중 앞 글자(prev)와 겹치는 부분이 끝나는 위치 (그 앞은 버린다). 안 겹치면 0 */
function overlapEnd(prev: string[], next: string[]): number {
  if (prev.length === 0 || next.length === 0) return 0
  // 같은 말을 다시 받은 조각(뒤 조각 전체가 앞 글자 끝에 들어 있음)은 통째로 건너뛴다
  const whole = key(next)
  if (whole.length >= 2 && key(prev.slice(-(next.length + MAX_SHIFT))).includes(whole)) return next.length
  let best = { size: 0, end: 0 }
  for (let shift = 0; shift <= Math.min(MAX_SHIFT, next.length - 1); shift++) {
    for (let size = Math.min(prev.length, next.length - shift); size > best.size; size--) {
      const a = key(prev.slice(-size))
      const b = key(next.slice(shift, shift + size))
      if (!a || !b) continue
      const same =
        shift > 0
          ? Math.min(a.length, b.length) >= MIN_SHIFTED_CHARS && similarity(a, b) >= OVERLAP_SIMILAR
          : size === 1
            ? (a === b && a.length >= 2) || (Math.min(a.length, b.length) >= 4 && similarity(a, b) >= ONE_WORD_SIMILAR)
            : similarity(a, b) >= OVERLAP_SIMILAR
      if (same) {
        best = { size, end: shift + size }
        break
      }
    }
  }
  return best.end
}

/** 비교용: 문장부호 · 띄어쓰기를 뺀 글자 */
function key(words: string[]): string {
  return words.join('').replace(/[^0-9A-Za-z가-힣]/g, '')
}

/** 1 - 편집 거리 / 긴 쪽 길이 */
function similarity(a: string, b: string): number {
  const dist = editDistance(a, b)
  return 1 - dist / Math.max(a.length, b.length)
}

function editDistance(a: string, b: string): number {
  let row = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    const next = [i]
    for (let j = 1; j <= b.length; j++) {
      next[j] = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    }
    row = next
  }
  return row[b.length]
}
