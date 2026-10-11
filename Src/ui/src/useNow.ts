import { useEffect, useState } from 'react'

/** 경과 시간 표시용 현재 시각 (epoch ms). intervalMs마다 갱신된다. */
export function useNow(intervalMs = 500): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}
