import { useRef, useState } from 'react'
import { api, isStaticMode } from '../api'

interface UploadStageProps {
  hasExistingCase: boolean
  onAnalysisStarted: () => void
  onResume: () => void
}

export function UploadStage(
  { hasExistingCase, onAnalysisStarted, onResume }: UploadStageProps,
) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const totalBytes = files.reduce((sum, f) => sum + f.size, 0)

  const pick = () => {
    const input = inputRef.current
    if (!input) return
    input.setAttribute('webkitdirectory', '')
    input.click()
  }

  const startUpload = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.upload(files)
      onAnalysisStarted()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const startPractice = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.analyzePractice()
      onAnalysisStarted()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not start analysis')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stage-narrow">
      <h1 className="display">Open a case</h1>
      {isStaticMode() && (
        <p className="warn-line">
          Public demo — the practice case (Muster Verpackungen GmbH FY2025)
          is preloaded below. Analyzing new dossiers needs the local console.
        </p>
      )}
      <p className="lede">
        fraudmind runs deterministic control tests over a GDPdU audit dossier.
        Every finding cites its source document and row — nothing is asserted
        without evidence you can check.
      </p>

      <section className="panel">
        <h2 className="panel-title">Upload dossier</h2>
        <p className="panel-hint">
          Select the dossier folder (GDPdU exports, Begleitdokumente,
          subledgers). Files stay on this machine.
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <div className="upload-row">
          <button className="btn" onClick={pick} disabled={busy}>
            Choose dossier folder
          </button>
          {files.length > 0 && (
            <span className="file-meta mono">
              {files.length} files · {(totalBytes / 1e6).toFixed(1)} MB
            </span>
          )}
        </div>
        {files.length > 0 && (
          <button
            className="btn btn-primary"
            onClick={startUpload}
            disabled={busy}
          >
            {busy ? 'Uploading…' : 'Upload & analyze'}
          </button>
        )}
      </section>

      <div className="divider-label">or</div>

      <section className="panel">
        <h2 className="panel-title">Practice dossier</h2>
        <p className="panel-hint">
          Muster Verpackungen GmbH FY2025 — already on this machine.
        </p>
        <button
          className="btn"
          onClick={startPractice}
          disabled={busy}
        >
          Analyze practice dossier
        </button>
      </section>

      {hasExistingCase && (
        <section className="panel panel-resume">
          <h2 className="panel-title">Current case</h2>
          <p className="panel-hint">
            A completed analysis is already on file for this workspace.
          </p>
          <button className="btn btn-primary" onClick={onResume}>
            Open current case
          </button>
        </section>
      )}

      {error && <p className="error-line" role="alert">{error}</p>}
    </div>
  )
}
