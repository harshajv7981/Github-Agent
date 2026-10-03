import {
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  Loader,
  Play,
  RefreshCw,
  Sparkles,
  XCircle,
} from 'lucide-react'
import type { SandboxReport } from './types'

type SandboxTab = 'tests' | 'linter' | 'types' | 'syntax' | 'logs'

type Props = {
  repoFullName?: string
  title?: string
  fileRewrites?: Record<string, string>
  sandboxState?: { loading: boolean; report?: SandboxReport; error?: string; activity?: string[] }
  healingState?: { loading: boolean; analysis?: string }
  providerLabel: string
  activeSubTab: SandboxTab
  setActiveSubTab: (tab: SandboxTab) => void
  onRunSandbox: () => void
  onAutoHeal: (report: SandboxReport) => void
}

export function SandboxPanel({
  sandboxState,
  healingState,
  providerLabel,
  activeSubTab,
  setActiveSubTab,
  onRunSandbox,
  onAutoHeal,
}: Props) {
  if (!sandboxState && !healingState) {
    return (
      <div className="sandbox-empty-state">
        <div className="sandbox-empty-copy">
          <FlaskConical size={16} />
          <div>
            <div className="sandbox-empty-title">Isolated Test Sandbox</div>
            <div className="sandbox-empty-description">
              Execute pytest, flake8, and mypy in an isolated workspace before opening PR.
            </div>
          </div>
        </div>
        <button type="button" className="sandbox-verify-btn" onClick={onRunSandbox}>
          <Play size={11} /> Run Sandbox Tests
        </button>
      </div>
    )
  }

  const report = sandboxState?.report
  const loading = sandboxState?.loading || healingState?.loading
  const error = sandboxState?.error

  return (
    <div className="sandbox-container">
      <div className="sandbox-header">
        <div className="sandbox-status-group">
          {loading ? (
            <span className="sandbox-status-badge sandbox-running">
              <Loader size={11} className="spin" />
              {healingState?.loading ? `Validating and auto-fixing with ${providerLabel}…` : 'Running Isolated Pytest & Linters…'}
            </span>
          ) : report?.overall_status === 'passed' ? (
            <span className="sandbox-status-badge sandbox-passed"><CheckCircle2 size={12} /> 100% Tests & Linters Passed</span>
          ) : report?.overall_status === 'warnings' ? (
            <span className="sandbox-status-badge sandbox-warnings"><AlertTriangle size={12} /> Validation completed with warnings</span>
          ) : report?.overall_status === 'failed' ? (
            <span className="sandbox-status-badge sandbox-failed"><XCircle size={12} /> Sandbox Verification Failed</span>
          ) : error ? (
            <span className="sandbox-status-badge sandbox-failed"><XCircle size={12} /> Sandbox Error</span>
          ) : (
            <span className="sandbox-status-badge sandbox-running"><FlaskConical size={12} /> Ready to verify</span>
          )}
          {report && <span className="sandbox-score-pill">Score: {report.score}/100</span>}
        </div>
        <div className="sandbox-metrics">
          {report && <span>⚡ {report.execution_time_seconds}s</span>}
          <button type="button" className="sandbox-verify-btn" disabled={loading} onClick={onRunSandbox} title="Re-run sandbox test suite">
            <RefreshCw size={10} className={loading ? 'spin' : ''} />
            {report ? 'Re-run Sandbox' : 'Run Sandbox'}
          </button>
        </div>
      </div>

      {report?.overall_status === 'failed' && !loading && (
        <div className="sandbox-autoheal-card">
          <div className="sandbox-heal-copy">
            <Sparkles size={16} />
            <div>
              <div className="sandbox-heal-title">Test failures or syntax issues detected</div>
              <div className="sandbox-heal-description">Let AI analyze the pytest tracebacks and automatically heal the code.</div>
            </div>
          </div>
          <button type="button" className="sandbox-heal-btn" disabled={healingState?.loading} onClick={() => onAutoHeal(report)}>
            {healingState?.loading ? <><Loader size={12} className="spin" /> Healing…</> : <><Sparkles size={12} /> Auto-Heal with AI</>}
          </button>
        </div>
      )}

      {healingState?.analysis && !healingState?.loading && (
        <div className="sandbox-healed-box"><strong>AI Healing Analysis:</strong> {healingState.analysis}</div>
      )}

      {sandboxState?.activity && sandboxState.activity.length > 0 && (
        <div className="sandbox-live-console" aria-live="polite">
          <div className="sandbox-live-console-title">Live sandbox console</div>
          {sandboxState.activity.map((entry, index) => <div key={`${entry}-${index}`}>$ {entry}</div>)}
          {loading && <div className="sandbox-console-cursor">$ running…</div>}
        </div>
      )}

      {report && (
        <>
          <div className="sandbox-tabs">
            <button type="button" className={`sandbox-tab-btn ${activeSubTab === 'tests' ? 'active' : ''}`} onClick={() => setActiveSubTab('tests')}>Pytest Suite {report.checks.tests.tests_run === 0 ? '(No tests collected)' : `(${report.checks.tests.passed_count}/${report.checks.tests.tests_run})`}</button>
            <button type="button" className={`sandbox-tab-btn ${activeSubTab === 'linter' ? 'active' : ''}`} onClick={() => setActiveSubTab('linter')}>Flake8 ({report.checks.linter.warnings_count} warnings)</button>
            <button type="button" className={`sandbox-tab-btn ${activeSubTab === 'types' ? 'active' : ''}`} onClick={() => setActiveSubTab('types')}>Mypy ({report.checks.type_check.errors_count || 0} issues)</button>
            <button type="button" className={`sandbox-tab-btn ${activeSubTab === 'syntax' ? 'active' : ''}`} onClick={() => setActiveSubTab('syntax')}>Syntax ({report.checks.syntax.errors?.length || 0})</button>
            <button type="button" className={`sandbox-tab-btn ${activeSubTab === 'logs' ? 'active' : ''}`} onClick={() => setActiveSubTab('logs')}>Terminal Log</button>
          </div>
          <div className="sandbox-body">
            {activeSubTab === 'tests' && (
              <div>
                <div className="sandbox-summary-stats">
                  <div className="sandbox-stat-box"><div className="sandbox-stat-val sandbox-pass-value">{report.checks.tests.passed_count}</div><div className="sandbox-stat-label">Passed</div></div>
                  <div className="sandbox-stat-box"><div className={`sandbox-stat-val ${report.checks.tests.failed_count > 0 ? 'sandbox-fail-value' : ''}`}>{report.checks.tests.failed_count}</div><div className="sandbox-stat-label">Failed</div></div>
                  <div className="sandbox-stat-box"><div className={`sandbox-stat-val ${report.checks.tests.error_count > 0 ? 'sandbox-fail-value' : ''}`}>{report.checks.tests.error_count}</div><div className="sandbox-stat-label">Errors</div></div>
                  <div className="sandbox-stat-box"><div className="sandbox-stat-val">{report.checks.tests.duration_seconds}s</div><div className="sandbox-stat-label">Duration</div></div>
                </div>
                {report.checks.tests.failed_count > 0 ? <div className="sandbox-failure-block"><div className="sandbox-failure-title">Pytest Failure Traceback:</div><div className="sandbox-terminal">{report.checks.tests.output}</div></div> : <div className="sandbox-success-message">✓ {report.checks.tests.summary}</div>}
              </div>
            )}
            {activeSubTab === 'linter' && (
              report.checks.linter.warnings?.length > 0 ? <table className="sandbox-lint-table"><thead><tr><th>File</th><th>Line:Col</th><th>Violation Description</th></tr></thead><tbody>{report.checks.linter.warnings.map((warning, index) => <tr key={index}><td>{warning.file}</td><td>{warning.line}:{warning.col}</td><td>{warning.message}</td></tr>)}</tbody></table> : <div className="sandbox-success-message">✓ Zero lint violations. Code strictly complies with flake8 standards.</div>
            )}
            {activeSubTab === 'types' && (report.checks.type_check.errors?.length > 0 ? <div className="sandbox-terminal">{report.checks.type_check.errors.join('\n')}</div> : <div className="sandbox-success-message">✓ Mypy static type analysis passed without errors.</div>)}
            {activeSubTab === 'syntax' && (report.checks.syntax.errors?.length > 0 ? <div className="sandbox-terminal sandbox-syntax-error">{report.checks.syntax.errors.map((error, index) => <div key={index}><strong>{error.file}</strong>: {error.message}</div>)}</div> : <div className="sandbox-success-message">✓ Python bytecode compiled cleanly with py_compile across all modified files.</div>)}
            {activeSubTab === 'logs' && <div className="sandbox-terminal">{report.checks.tests.output || 'No output recorded.'}</div>}
          </div>
        </>
      )}
    </div>
  )
}
