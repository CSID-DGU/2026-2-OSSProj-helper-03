// 임시 시작 패널. 준비 화면(그림 5)을 만들기 전까지 공연 이름과 큐 파일만 받아 회차를 시작한다.
// 마지막으로 시작한 설정(공연 이름 · 큐 파일 내용 · 소리 입력)을 브라우저에 기억해 다음에 다시 채운다
// (회차를 끝내고 돌아올 때마다 샘플 대본으로 돌아가 다른 대본으로 시작하던 실수 방지).
// 인터넷 서버로 빌드하면(VITE_INPUTS, VITE_NEED_CODE) 브라우저 소리 입력과 접속 코드 칸이 보인다.

import { useState } from 'react'
import sampleCsv from '../mock/sample_cues.csv?raw'
import { parseCueFile, type Cue } from './cues'
import { AVAILABLE_INPUTS, INPUT_OPTIONS, type InputChoice } from './inputs'
import { ENGINE_URL, NEED_CODE, type Connection } from './useEngine'

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: '연결 중',
  open: '연결됨',
  closed: '끊김 (다시 연결하는 중)',
  denied: '접속 코드가 맞지 않음',
}

const DEFAULT_INPUT: InputChoice = AVAILABLE_INPUTS.includes('file') ? 'file' : AVAILABLE_INPUTS[0]
const SAMPLE = { name: '샘플 공연', cueFile: 'sample_cues.csv', csv: sampleCsv, input: DEFAULT_INPUT }
const STORAGE_KEY = 'helper.start'

interface Saved {
  name: string
  cueFile: string
  csv: string
  input: InputChoice
}

/** 지난번 설정. 없거나 읽을 수 없으면(사생활 보호 모드 등) 샘플 */
function loadSaved(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Saved | null
    if (saved && saved.csv && saved.cueFile) {
      parseCueFile(saved.csv)   // 형식이 깨졌으면 샘플로
      return { ...saved, input: AVAILABLE_INPUTS.includes(saved.input) ? saved.input : DEFAULT_INPUT }
    }
  } catch {
    // 저장 안 됨 · 깨진 값: 샘플로 시작
  }
  return SAMPLE
}

function save(value: Saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // 저장이 막혀 있어도 회차 시작에는 지장 없음
  }
}

export interface StartRequest {
  name: string
  cueFile: string
  cues: Cue[]
  /** 큐 파일 내용 (CSV 또는 자막 JSON, 엔진에 그대로 보냄) */
  csv: string
  input: InputChoice
  /** '내 녹음 파일'로 고른 파일 */
  audioFile: File | null
}

interface Props {
  connection: Connection
  /** 지금 쓰는 접속 코드 */
  code: string
  onCode: (code: string) => void
  /** 회차를 못 열었을 때 (마이크 허용 안 됨 · 녹음 파일을 못 엶 등) */
  error: string | null
  onStart: (req: StartRequest) => void
}

export function StartPanel({ connection, code, onCode, error: startError, onStart }: Props) {
  const [initial] = useState(loadSaved)
  const [name, setName] = useState(initial.name)
  const [cueFile, setCueFile] = useState(initial.cueFile)
  const [csv, setCsv] = useState(initial.csv)
  const [cues, setCues] = useState<Cue[]>(() => parseCueFile(initial.csv))
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState<InputChoice>(initial.input)
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [codeDraft, setCodeDraft] = useState(code)

  const applyCsv = (fileName: string, text: string) => {
    setCues(parseCueFile(text))
    setCueFile(fileName)
    setCsv(text)
    setError(null)
  }

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    try {
      applyCsv(file.name, await file.text())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const start = () => {
    save({ name: name.trim(), cueFile, csv, input })
    onStart({ name: name.trim(), cueFile, cues, csv, input, audioFile })
  }

  const options = INPUT_OPTIONS.filter((o) => AVAILABLE_INPUTS.includes(o.choice))
  const showCode = NEED_CODE || connection === 'denied'

  return (
    <main className="start">
      <h1>회차 시작</h1>
      <p className="muted">
        엔진 {ENGINE_URL} · <span className={`conn conn-${connection}`}>{CONNECTION_LABEL[connection]}</span>
      </p>

      {showCode && (
        <form
          className="code-row"
          onSubmit={(e) => {
            e.preventDefault()
            onCode(codeDraft.trim())
          }}
        >
          <label>
            접속 코드
            <input value={codeDraft} onChange={(e) => setCodeDraft(e.target.value)} autoComplete="off" />
          </label>
          <button type="submit" className="small">
            연결
          </button>
        </form>
      )}

      <label>
        공연 이름
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      <label>
        자막 큐 파일 (CSV 또는 자막 JSON)
        <input type="file" accept=".csv,text/csv,.json,application/json" onChange={(e) => loadFile(e.target.files?.[0])} />
      </label>
      <p className={error ? 'error' : 'muted'}>
        {error ?? `${cueFile} · 큐 ${cues.length}개`}
        {!error && cueFile !== SAMPLE.cueFile && (
          <button className="link small" onClick={() => applyCsv(SAMPLE.cueFile, SAMPLE.csv)}>
            샘플 대본으로
          </button>
        )}
      </p>

      <fieldset className="modes">
        <legend>소리 입력</legend>
        {options.map((opt) => (
          <label key={opt.choice} className="mode">
            <input
              type="radio"
              name="input"
              value={opt.choice}
              checked={input === opt.choice}
              onChange={() => setInput(opt.choice)}
            />
            <span>
              {opt.label}
              <span className="muted small">{opt.hint}</span>
            </span>
          </label>
        ))}
        {input === 'browser-file' && (
          <label>
            녹음 파일
            <input type="file" accept="audio/*" onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)} />
          </label>
        )}
        {(input === 'browser-mic' || input === 'browser-file') && (
          <p className="muted small">소리는 저장하지 않고, 음성인식(Google)에만 보냅니다.</p>
        )}
      </fieldset>

      {startError && <p className="error">{startError}</p>}

      <button
        disabled={
          connection !== 'open' ||
          cues.length === 0 ||
          name.trim() === '' ||
          (input === 'browser-file' && audioFile === null)
        }
        onClick={start}
      >
        보조 화면 시작
      </button>
      <p className="muted small">준비 화면이 만들어지면 이 패널은 준비 화면으로 바뀝니다.</p>
    </main>
  )
}
