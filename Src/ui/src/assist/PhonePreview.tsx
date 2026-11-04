// 관객 휴대폰 자막 미리보기. 오퍼레이터가 마지막으로 송출한 것(대본 큐 또는 애드리브 임시 자막)을
// 관객이 보게 될 모양 그대로 작게 보여 준다. 송출한 큐 바로 뒤의 짧은 대사는 함께 띄운다.

import type { Cue } from '../cues'

interface Props {
  cue: Cue | undefined
  /** 송출한 큐와 함께 띄운 짧은 대사 */
  followers?: Cue[]
  /** 오퍼레이터가 송출한 애드리브 임시 자막. 있으면 대본 자막 대신 보여 준다 */
  temp?: string
}

/** 배리어프리 자막 형식: 대사는 [화자], 가사는 ♪로 감싼다. 음향·암전·안내는 그대로 */
function subtitle(cue: Cue): string {
  if (cue.type === 'dialogue') return cue.speaker ? `[${cue.speaker}] ${cue.text}` : cue.text
  if (cue.type === 'lyric') {
    const body = cue.text.replace(/^♪\s*/, '').replace(/\s*♪$/, '')
    return `♪ ${body} ♪`
  }
  return cue.text
}

export function PhonePreview({ cue, followers = [], temp }: Props) {
  return (
    <section className="phone-wrap" aria-label="관객 휴대폰 자막 미리보기">
      <div className="phone-head">
        <h2>관객 휴대폰 미리보기</h2>
        <span className="muted small">송출된 자막</span>
      </div>
      <div className="phone">
        <div className="phone-screen">
          {temp ? (
            <p className="phone-sub">{temp}</p>
          ) : (
            <p className="phone-sub">
              {cue ? subtitle(cue) : '…'}
              {cue &&
                followers.map((f) => (
                  <span key={f.id} className="phone-sub-next">
                    {subtitle(f)}
                  </span>
                ))}
            </p>
          )}
        </div>
      </div>
      {temp && <p className="phone-temp">지금 보이는 것: 애드리브 임시 자막 (오퍼레이터 송출)</p>}
    </section>
  )
}
