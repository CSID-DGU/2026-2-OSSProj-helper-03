/** 겹쳐 보낸 인식 조각을 이어 붙인다: 앞 글자 끝과 뒤 글자 앞이 같은 단어로 겹치면 한 번만 */
export function mergeTranscripts(parts: string[]): string {
  let words: string[] = []
  for (const part of parts) {
    const next = part.split(/\s+/).filter(Boolean)
    let overlap = Math.min(words.length, next.length)
    while (overlap > 0 && words.slice(-overlap).join(' ') !== next.slice(0, overlap).join(' ')) overlap--
    words = [...words, ...next.slice(overlap)]
  }
  return words.join(' ')
}
