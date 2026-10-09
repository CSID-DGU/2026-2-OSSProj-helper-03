// 화면 가장자리 깜빡임. 오퍼레이터는 대부분 송출 프로그램을 보고 있으므로,
// 곁눈으로도 알 수 있게 이탈 시작(빨강)과 복귀(파랑) 때 가장자리를 짧게 깜빡인다.
// 이탈 중에는 깜빡임이 끝난 뒤에도 얇은 빨간 테두리를 남긴다.

import { useState } from 'react'
import type { DeviationAlert } from '../protocol'

interface Props {
  deviation: DeviationAlert | null
}

export function EdgeFlash({ deviation }: Props) {
  // 같은 알림으로 다시 그려질 때는 깜빡이지 않도록, 끝난 깜빡임의 키를 기억한다
  const [doneKey, setDoneKey] = useState<string | null>(null)

  if (!deviation) return null

  const returned = deviation.return_cue_id !== null
  const key = `${deviation.since}-${returned ? 'return' : 'start'}`
  const flashing = key !== doneKey
  const tone = returned ? 'edge-return' : 'edge-during'

  if (!flashing && returned) return null

  return (
    <div
      key={key}
      className={`edge ${tone} ${flashing ? 'edge-flash' : 'edge-steady'}`}
      onAnimationEnd={() => setDoneKey(key)}
      aria-hidden
    />
  )
}
