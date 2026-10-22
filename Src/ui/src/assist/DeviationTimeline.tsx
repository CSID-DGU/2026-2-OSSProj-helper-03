// 이번 회차 이탈 기록. 알림 카드가 사라진 뒤에도 방금 무슨 일이 있었는지 확인할 수 있게 최신순으로 남긴다.

import type { DeviationLogEntry } from '../useEngine'
import { DEVIATION_LABEL } from './labels'

interface Props {
  log: DeviationLogEntry[]
  now: number
}

const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

const seconds = (ms: number) => `${Math.max(0, Math.round(ms / 1000))}초`

/** 누락·반복은 시작 알림 없이 복귀 알림 하나로 오므로 걸린 시간이 거의 0 → '즉시' */
const duration = (ms: number) => (ms < 1000 ? '즉시' : seconds(ms))

export function DeviationTimeline({ log, now }: Props) {
  return (
    <section className="panel timeline">
      <header className="panel-head">
        <h2>이탈 기록</h2>
        <span className="timeline-count">{log.length}건</span>
      </header>
      {log.length === 0 ? (
        <p className="timeline-empty">아직 없습니다</p>
      ) : (
        <ol className="timeline-list">
          {[...log].reverse().map((entry) => {
            const during = entry.returnCueId === null
            return (
              <li key={entry.since} className={during ? 'timeline-during' : undefined}>
                <time>{clock(entry.since)}</time>
                <span className="timeline-type">{DEVIATION_LABEL[entry.deviationType]}</span>
                <span className="timeline-duration">
                  {during ? `진행 중 ${seconds(now - entry.since)}` : duration((entry.returnedAt ?? now) - entry.since)}
                </span>
                <span className="timeline-return">{during ? '' : `→ #${entry.returnCueId}`}</span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
