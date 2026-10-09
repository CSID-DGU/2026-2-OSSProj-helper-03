// ② 이탈 알림 카드. 대본 이탈 유형·경과 시간을 보여 주고, 대본으로 돌아오면 복귀 큐 번호를 크게 띄운다.

import type { Cue } from '../cues'
import type { DeviationAlert, DeviationType } from '../protocol'
import { RETURN_HIGHLIGHT_MS } from '../settings'
import { DEVIATION_LABEL } from './labels'

const HEADLINE: Record<DeviationType, { during: string; returned: string }> = {
  adlib: { during: '대본에 없는 말', returned: '대본에 없는 말 → 대본으로 돌아옴' },
  skip: { during: '대사를 건너뜀', returned: '대사를 건너뜀 → 뒤 대사로 이동' },
  repeat: { during: '앞 대사를 반복', returned: '앞 대사를 반복 → 앞 대사로 돌아감' },
}

/** 이탈 알림이 없을 때 카드에 보여 줄 상태. 위에서부터 우선순위가 높다. */
export type HoldReason = 'disconnected' | 'stale' | 'no-input' | 'song' | null

const HOLD_TEXT: Record<Exclude<HoldReason, null>, { title: string; body: string }> = {
  disconnected: { title: '엔진 연결 끊김', body: '다시 연결하는 중입니다. 기존 방식대로 송출하세요.' },
  stale: { title: '엔진 응답 없음', body: '위치 정보가 들어오지 않습니다. 기존 방식대로 송출하세요.' },
  'no-input': { title: '음향 입력 없음', body: '소리가 들어오지 않아 알림을 멈췄습니다.' },
  song: { title: '노래 구간', body: '노래 구간에서는 위치 추적을 쉽니다.' },
}

interface Props {
  deviation: DeviationAlert | null
  /** deviation을 받은 시각 */
  deviationAt: number | null
  hold: HoldReason
  cueById: Map<number, Cue>
  now: number
}

const seconds = (ms: number) => `${Math.max(0, Math.floor(ms / 1000))}초`

export function DeviationCard({ deviation, deviationAt, hold, cueById, now }: Props) {
  // 연결이 끊겼거나 응답이 없으면 지난 알림보다 그 사실을 먼저 알린다
  if (hold === 'disconnected' || hold === 'stale') return <HoldCard reason={hold} />

  if (deviation && deviation.return_cue_id === null) {
    return (
      <section className="card card-during" aria-live="assertive">
        <p className="card-meta">
          대본 이탈 알림 · {DEVIATION_LABEL[deviation.deviation_type]} · 경과 {seconds(now - deviation.since)}
        </p>
        <h2 className="card-title">{HEADLINE[deviation.deviation_type].during}</h2>
        <p className="card-body">대본으로 돌아오면 큐 번호를 알려 드립니다. 그동안은 기존 방식대로 송출하세요.</p>
      </section>
    )
  }

  const returnedAt = deviationAt ?? now
  if (deviation && deviation.return_cue_id !== null && now - returnedAt < RETURN_HIGHLIGHT_MS) {
    const cue = cueById.get(deviation.return_cue_id)
    return (
      <section className="card card-returned" aria-live="assertive">
        <p className="card-meta">
          대본 이탈 알림 · {DEVIATION_LABEL[deviation.deviation_type]} · 이탈 {seconds(returnedAt - deviation.since)}
        </p>
        <h2 className="card-title">{HEADLINE[deviation.deviation_type].returned}</h2>
        <p className="card-cue">#{deviation.return_cue_id}</p>
        {cue && <p className="card-cue-text">{cue.text}</p>}
        <p className="card-body">송출 프로그램에서 이 큐로 이동하세요</p>
      </section>
    )
  }

  const recent =
    deviation && deviation.return_cue_id !== null
      ? `최근: ${DEVIATION_LABEL[deviation.deviation_type]} 뒤 #${deviation.return_cue_id}로 복귀 (${seconds(now - returnedAt)} 전)`
      : null

  if (hold) return <HoldCard reason={hold} recent={recent} />

  return (
    <section className="card card-idle">
      <p className="card-meta">대본 이탈 알림</p>
      <h2 className="card-title">대본대로 진행 중</h2>
      {recent && <p className="card-recent">{recent}</p>}
    </section>
  )
}

function HoldCard({ reason, recent }: { reason: Exclude<HoldReason, null>; recent?: string | null }) {
  const text = HOLD_TEXT[reason]
  const tone = reason === 'disconnected' || reason === 'stale' ? 'card-error' : 'card-hold'
  return (
    <section className={`card ${tone}`} aria-live="polite">
      <p className="card-meta">대본 이탈 알림 · 알림 보류</p>
      <h2 className="card-title">{text.title}</h2>
      <p className="card-body">{text.body}</p>
      {recent && <p className="card-recent">{recent}</p>}
    </section>
  )
}
