// 관객 휴대폰 자막 미리보기. 관객이 보게 될 자막 모양을 오퍼레이터 화면 안에 작게 보여 준다.
// 실제로 송출된 큐는 2단계(송출 프로그램 연동) 전이라 받을 수 없어서, 지금은 AI가 추정한 큐로 보여 준다.

import type { Cue } from '../cues'

interface Props {
  cue: Cue | undefined
  /** 대본 이탈 중이면 흐리게 */
  deviating: boolean
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

export function PhonePreview({ cue, deviating, temp }: Props) {
  return (
    <section className="phone-wrap" aria-label="관객 휴대폰 자막 미리보기">
      <div className="phone-head">
        <h2>관객 휴대폰 미리보기</h2>
        <span className="muted small">AI 추정 기준</span>
      </div>
      <div className="phone">
        <div className="phone-screen">
          {temp ? (
            <p className="phone-sub">{temp}</p>
          ) : (
            <p className={`phone-sub ${deviating ? 'phone-sub-dim' : ''}`}>{cue ? subtitle(cue) : '…'}</p>
          )}
        </div>
      </div>
      {temp && <p className="phone-temp">지금 보이는 것: 애드리브 임시 자막 (오퍼레이터 송출)</p>}
    </section>
  )
}
