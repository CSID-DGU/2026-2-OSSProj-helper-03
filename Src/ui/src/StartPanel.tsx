// 임시 시작 패널. 준비 화면(그림 5)을 만들기 전까지 공연 이름과 큐 파일만 받아 회차를 시작한다.

import { useState } from 'react'
import sampleCsv from '../mock/sample_cues.csv?raw'
import { parseCueCsv, type Cue } from './cues'
import { ENGINE_URL, type Connection } from './useEngine'

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: '연결 중',
  open: '연결됨',
  closed: '끊김 (다시 연결하는 중)',
}

interface Props {
  connection: Connection
  onStart: (show: { name: string; cueFile: string; cues: Cue[] }) => void
}

export function StartPanel({ connection, onStart }: Props) {
  const [name, setName] = useState('샘플 공연')
  const [cueFile, setCueFile] = useState('sample_cues.csv')
  const [cues, setCues] = useState<Cue[]>(() => parseCueCsv(sampleCsv))
  const [error, setError] = useState<string | null>(null)

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    try {
      setCues(parseCueCsv(await file.text()))
      setCueFile(file.name)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <main className="start">
      <h1>회차 시작</h1>
      <p className="muted">
        엔진 {ENGINE_URL} · <span className={`conn conn-${connection}`}>{CONNECTION_LABEL[connection]}</span>
      </p>

      <label>
        공연 이름
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      <label>
        자막 큐 파일 (CSV)
        <input type="file" accept=".csv,text/csv" onChange={(e) => loadFile(e.target.files?.[0])} />
      </label>
      <p className={error ? 'error' : 'muted'}>{error ?? `${cueFile} · 큐 ${cues.length}개`}</p>

      <button
        disabled={connection !== 'open' || cues.length === 0 || name.trim() === ''}
        onClick={() => onStart({ name: name.trim(), cueFile, cues })}
      >
        보조 화면 시작
      </button>
      <p className="muted small">준비 화면이 만들어지면 이 패널은 준비 화면으로 바뀝니다.</p>
    </main>
  )
}
