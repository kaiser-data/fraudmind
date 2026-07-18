import { useEffect, useRef, useState } from 'react'
import { api } from './api'

type ChatMsg = { role: 'user' | 'assistant'; content: string }

/** Floating chat window: ask the case documents (OpenAI grounded in
 *  engine findings + Cognee knowledge-graph recall). */
export function ChatDock() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, busy])

  const send = async () => {
    const q = input.trim()
    if (!q || busy) return
    const next: ChatMsg[] = [...messages, { role: 'user', content: q }]
    setMessages(next)
    setInput('')
    setBusy(true)
    try {
      const res = await api.chat(next)
      setMessages([...next, { role: 'assistant', content: res.reply }])
    } catch {
      setMessages([...next, {
        role: 'assistant',
        content: 'Chat backend unreachable — is the local server running?',
      }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chatdock">
      {open && (
        <div className="chatdock-panel" role="dialog" aria-label="Case chat">
          <div className="chatdock-head">
            <span>Chat with the case documents</span>
            <button onClick={() => setOpen(false)} aria-label="Close">×</button>
          </div>
          <div className="chatdock-msgs" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="chatdock-hint">
                Grounded in the engine findings and the Cognee knowledge
                graph — e.g. “Which journals were posted without release?”
                or “Summarize what BSP-U02 did.”
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`chatdock-msg ${m.role}`}>{m.content}</div>
            ))}
            {busy && <div className="chatdock-msg assistant">…</div>}
          </div>
          <div className="chatdock-input">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              placeholder="Ask about the dossier…"
              disabled={busy}
            />
            <button onClick={send} disabled={busy || !input.trim()}>Send</button>
          </div>
        </div>
      )}
      <button className="chatdock-fab" onClick={() => setOpen((v) => !v)}>
        {open ? 'Close chat' : '💬 Ask the case'}
      </button>
    </div>
  )
}
