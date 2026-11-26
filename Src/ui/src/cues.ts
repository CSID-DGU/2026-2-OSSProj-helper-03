// 자막 큐 데이터. 기준: 수행계획서 (6) 데이터 정의의 Cue.
// 정규화 본문은 엔진(① 큐 시트 로더)이 만들기 때문에 화면에서는 다루지 않는다.

export type CueType = 'dialogue' | 'lyric' | 'sound' | 'blackout' | 'notice'

export interface Cue {
  id: number
  order: number
  type: CueType
  speaker: string
  text: string
}

export const CUE_TYPE_LABEL: Record<CueType, string> = {
  dialogue: '대사',
  lyric: '가사',
  sound: '음향',
  blackout: '암전',
  notice: '안내',
}

const TYPE_ALIASES: Record<string, CueType> = {
  dialogue: 'dialogue', 대사: 'dialogue',
  lyric: 'lyric', 가사: 'lyric',
  sound: 'sound', 음향: 'sound',
  blackout: 'blackout', 암전: 'blackout',
  notice: 'notice', 안내: 'notice',
}

/** 큐 CSV 열 (임시). 데이터 담당과 열이 확정되면 여기를 고친다. */
export const CUE_CSV_COLUMNS = ['id', 'order', 'type', 'speaker', 'text'] as const

/** 따옴표("...")와 줄바꿈이 들어간 칸까지 처리하는 CSV 파서 */
export function parseCsv(source: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  const text = source.replace(/^﻿/, '')

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (ch === '"') {
        quoted = false
      } else {
        field += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(field)
      field = ''
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += ch
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((cell) => cell.trim() !== ''))
}

/** 큐 CSV를 읽어 Cue 목록으로. 형식이 틀리면 줄 번호와 함께 Error를 던진다. */
export function parseCueCsv(source: string): Cue[] {
  const [header, ...body] = parseCsv(source)
  if (!header) throw new Error('빈 파일입니다.')

  const index = Object.fromEntries(header.map((name, i) => [name.trim(), i]))
  const missing = CUE_CSV_COLUMNS.filter((name) => !(name in index))
  if (missing.length > 0) {
    throw new Error(`필요한 열이 없습니다: ${missing.join(', ')}`)
  }

  return body
    .map((cells, i) => {
      const line = i + 2
      const get = (name: (typeof CUE_CSV_COLUMNS)[number]) => (cells[index[name]] ?? '').trim()
      const id = Number(get('id'))
      const order = Number(get('order'))
      const type = TYPE_ALIASES[get('type')]
      if (!Number.isInteger(id)) throw new Error(`${line}번째 줄: id가 숫자가 아닙니다.`)
      if (!Number.isInteger(order)) throw new Error(`${line}번째 줄: order가 숫자가 아닙니다.`)
      if (!type) throw new Error(`${line}번째 줄: 알 수 없는 유형 "${get('type')}"`)
      return { id, order, type, speaker: get('speaker'), text: get('text') }
    })
    .sort((a, b) => a.order - b.order)
}

/** 큐 파일 내용 → Cue 목록. "{"로 시작하면 오롯플래닛 자막 파일(JSON), 아니면 CSV. */
export function parseCueFile(source: string): Cue[] {
  return /^[﻿\s]*\{/.test(source) ? parseSubtitleJson(source) : parseCueCsv(source)
}

/** 자막 파일 한 줄 (오롯플래닛 형식). type, speaker는 우리가 더해 쓸 수 있는 칸 (#46에서 정하는 중) */
interface SubtitleLine {
  idx?: unknown
  subtitles?: { lang?: unknown; text?: unknown }[]
  type?: unknown
  speaker?: unknown
}

/**
 * 오롯플래닛 자막 파일(JSON)을 Cue 목록으로. 엔진 engine/cue_loader.py parse_subtitle_json과 같은 규칙.
 * - idx를 큐 번호로 씀 (송출 신호 index의 subtitle_idx와 같은 번호). 순서는 파일 순서
 * - 추적 대사는 lang(기본 kor) 문장. 비어 있으면 안내(notice)로 둬서 추적하지 않음
 * - 유형, 화자가 없으면 대사로 봄
 */
export function parseSubtitleJson(source: string, lang = 'kor'): Cue[] {
  let data: unknown
  try {
    data = JSON.parse(source.replace(/^﻿/, ''))
  } catch (e) {
    throw new Error(`자막 파일(JSON)을 읽을 수 없습니다: ${e instanceof Error ? e.message : String(e)}`)
  }
  const contents = (data as { contents?: unknown } | null)?.contents
  if (!Array.isArray(contents) || contents.length === 0) throw new Error('자막 파일에 "contents" 목록이 없습니다.')

  const seen = new Set<number>()
  const cues = contents.map((item: SubtitleLine, i): Cue => {
    const n = i + 1
    const idx = item?.idx
    if (typeof idx !== 'number' || !Number.isInteger(idx)) throw new Error(`${n}번째 자막: idx가 숫자가 아닙니다.`)
    if (seen.has(idx)) throw new Error(`${n}번째 자막: 앞에서 이미 나온 idx(${idx})입니다.`)
    seen.add(idx)
    const sub = (Array.isArray(item.subtitles) ? item.subtitles : []).find((s) => s?.lang === lang)
    const text = String(sub?.text ?? '').trim()
    const rawType = String(item.type ?? '').trim()
    const type = rawType ? TYPE_ALIASES[rawType] : text ? 'dialogue' : 'notice'
    if (!type) throw new Error(`${n}번째 자막 (idx ${idx}): 알 수 없는 유형 "${rawType}"`)
    return { id: idx, order: n, type, speaker: String(item.speaker ?? '').trim(), text }
  })
  if (!cues.some((c) => c.text)) throw new Error(`자막 파일에 ${lang} 문장이 없습니다 (위치 추적에 쓰는 언어).`)
  return cues
}
