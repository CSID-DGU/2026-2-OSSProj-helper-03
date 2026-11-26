// 관객 휴대폰 자막 미리보기. 오퍼레이터가 마지막으로 송출한 것(대본 큐 또는 애드리브 임시 자막)을
// 관객이 보게 될 모양 그대로 작게 보여 준다. 오롯플래닛 관객 화면은 신호 하나에 한 줄만 띄우고,
// 암전 줄을 송출하면 화면을 끈다(blackout 신호).

import type { Cue } from '../cues'

interface Props {
  cue: Cue | undefined
  /** 오퍼레이터가 송출한 애드리브 임시 자막. 있으면 대본 자막 대신 보여 준다 */
  temp?: string
}

/** 배리어프리 자막 형식: 대사는 [화자], 가사는 ♪로 감싼다. 음향 · 안내는 그대로 */
function subtitle(cue: Cue): string {
  if (cue.type === 'dialogue') return cue.speaker ? `[${cue.speaker}] ${cue.text}` : cue.text
  if (cue.type === 'lyric') {
    const body = cue.text.replace(/^♪\s*/, '').replace(/\s*♪$/, '')
    return `♪ ${body} ♪`
  }
  return cue.text
}

/** 실제 관객 화면(11/13 현장 체험)처럼 대사 · 가사는 흰색, 상황 설명(음향)은 주황색 */
const tone = (cue: Cue) => (cue.type === 'sound' ? 'phone-desc' : undefined)

export function PhonePreview({ cue, temp }: Props) {
  const off = !temp && cue?.type === 'blackout'
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
          ) : off ? null : (
            <p className="phone-sub">{cue ? <span className={tone(cue)}>{subtitle(cue)}</span> : '…'}</p>
          )}
        </div>
      </div>
      {temp && <p className="phone-temp">지금 보이는 것: 애드리브 임시 자막 (오퍼레이터 송출)</p>}
      {off && <p className="phone-temp">지금 보이는 것: 꺼진 화면 (암전)</p>}
    </section>
  )
}
