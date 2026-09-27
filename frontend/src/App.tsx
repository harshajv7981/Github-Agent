import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CheckCircle2,
  ChevronDown,
  CircleCheck,
  CircleDot,
  Clock3,
  Code2,
  ExternalLink,
  Flame,
  FlaskConical,
  GitPullRequest,
  LayoutDashboard,
  ListTodo,
  Loader,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Star,
  Terminal,
  Wand2,
  X,
  XCircle,
} from 'lucide-react'
import './App.css'

type Repo = {
  name: string
  owner: string
  description: string
  stars: string
  language: string
  issues: number
  score: number
  trend: string
  color: string
  initials: string
}

type SandboxReport = {
  success: boolean
  overall_status: 'passed' | 'warnings' | 'failed'
  score: number
  execution_time_seconds: number
  environment: string
  checks: {
    syntax: {
      passed: boolean
      checked_files: string[]
      errors: { file: string; message: string }[]
      summary: string
    }
    linter: {
      passed: boolean
      tool: string
      warnings_count: number
      warnings: { file: string; line: string; col: string; message: string }[]
      summary: string
    }
    type_check: {
      passed: boolean
      tool: string
      errors_count: number
      errors: string[]
      summary: string
    }
    tests: {
      passed: boolean
      tests_run: number
      passed_count: number
      failed_count: number
      error_count: number
      duration_seconds: number
      output: string
      summary: string
    }
  }
  summary: string
  modified_files: string[]
}

type Issue = {
  id: number
  repo: string
  title: string
  number: string
  rawNumber: number
  label: string
  age: string
  difficulty: 'Good first issue' | 'Intermediate'
  body?: string
  ai_analysis?: string
  agent_status?: string
  sandbox_result?: SandboxReport
}

type PullRequest = {
  id: number
  repository: string
  title: string
  number?: number
  url?: string
  status: string
  issue_number?: number
  issue_url?: string
  ai_summary?: string
  sandbox_result?: SandboxReport
  created_at: string
}

type OllamaHealth = {
  ollama_connected: boolean
  configured_model: string
  model_available: boolean
}

type ActiveRun = {
  id: number
  name: string
  status: string
  repositories_scanned: number
  issues_found: number
  summary?: string
  created_at: string
}

type AnalyzeResult = {
  issue_id: number
  analysis: string
  pr_title: string
  pr_body: string
  acceptance_criteria?: string[]
  is_actionable?: boolean
  relevant_files: string[]
  file_rewrites: Record<string, string>
}

type FeatureSuggestion = {
  id: number
  repository: string
  title: string
  description: string
  category: string
  complexity: string
  impact_score: number
  implementation_plan: string
  suggested_files: string[]
  status: string
  ai_analysis?: string
  pr_title?: string
  pr_body?: string
  sandbox_result?: SandboxReport
  created_at: string
}

type ImplementFeatureResult = {
  feature_id: number
  analysis: string
  pr_title: string
  pr_body: string
  acceptance_criteria?: string[]
  is_actionable?: boolean
  relevant_files: string[]
  file_rewrites: Record<string, string>
}

function App() {
  const [activeTab, setActiveTab] = useState('Overview')
  const [query, setQuery] = useState('')
  const [pythonOnly, setPythonOnly] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [lastScan, setLastScan] = useState('Today, 09:02')
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [selectedFeature, setSelectedFeature] = useState<FeatureSuggestion | null>(null)
  const [ollamaHealth, setOllamaHealth] = useState<OllamaHealth | null>(null)
  const [telemetry, setTelemetry] = useState<any>(null)
  const [realRepos, setRealRepos] = useState<Repo[]>([])
  const [realIssues, setRealIssues] = useState<Issue[]>([])
  const [features, setFeatures] = useState<FeatureSuggestion[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [pullRequests, setPullRequests] = useState<PullRequest[]>([])
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null)

  // Per-issue analyze state: issueId -> { loading, result, error }
  const [analyzeState, setAnalyzeState] = useState<
    Record<number, { loading: boolean; result?: AnalyzeResult; error?: string }>
  >({})
  // Per-issue PR submit state
  const [prSubmitting, setPrSubmitting] = useState<Record<number, boolean>>({})
  const [reviewState, setReviewState] = useState<Record<number, {loading: boolean, result?: any}>>({})
  const [expandedFile, setExpandedFile] = useState<string | null>(null)

  // Per-repo feature suggesting state: repo_full_name -> boolean
  const [suggestingRepo, setSuggestingRepo] = useState<Record<string, boolean>>({})
  // Per-feature implementation state: featureId -> { loading, result, error }
  const [featureImplementState, setFeatureImplementState] = useState<
    Record<number, { loading: boolean; result?: ImplementFeatureResult; error?: string }>
  >({})
  // Per-feature PR submitting state
  const [featurePrSubmitting, setFeaturePrSubmitting] = useState<Record<number, boolean>>({})
  const [featureCategoryFilter, setFeatureCategoryFilter] = useState('all')
  const [quickSuggestRepo, setQuickSuggestRepo] = useState('')

  // Sandbox states
  const [issueSandboxState, setIssueSandboxState] = useState<
    Record<number, { loading: boolean; report?: SandboxReport; error?: string }>
  >({})
  const [featureSandboxState, setFeatureSandboxState] = useState<
    Record<number, { loading: boolean; report?: SandboxReport; error?: string }>
  >({})
  const [issueHealingState, setIssueHealingState] = useState<
    Record<number, { loading: boolean; analysis?: string }>
  >({})
  const [featureHealingState, setFeatureHealingState] = useState<
    Record<number, { loading: boolean; analysis?: string }>
  >({})
  const [issueSandboxTab, setIssueSandboxTab] = useState<
    'tests' | 'linter' | 'types' | 'syntax' | 'logs'
  >('tests')
  const [featureSandboxTab, setFeatureSandboxTab] = useState<
    'tests' | 'linter' | 'types' | 'syntax' | 'logs'
  >('tests')

  const fetchData = async () => {

    try {
      fetch('http://localhost:8000/api/telemetry')
        .then(res => res.json())
        .then(data => setTelemetry(data))
        .catch(() => {})
    } catch(e) {}

    try {
      const [reposRes, issuesRes, runsRes, prsRes, featuresRes] = await Promise.all([
        fetch('http://localhost:8000/api/repositories'),
        fetch('http://localhost:8000/api/issues'),
        fetch('http://localhost:8000/api/runs'),
        fetch('http://localhost:8000/api/pull-requests'),
        fetch('http://localhost:8000/api/features'),
        
      ])

      if (reposRes.ok) {
        const reposData = await reposRes.json()
        const mapped = reposData.map((r: any) => ({
          name: r.name,
          owner: r.owner,
          description: r.description,
          stars: r.stars > 1000 ? `${(r.stars / 1000).toFixed(1)}k` : r.stars.toString(),
          language: r.language,
          issues: r.open_issues,
          score: r.fit_score,
          trend: `+${r.trend_percent}%`,
          color: getRepoColor(r.name),
          initials: r.name.slice(0, 2).toUpperCase(),
        }))
        setRealRepos(mapped)
        if (!quickSuggestRepo && mapped.length > 0) {
          setQuickSuggestRepo(`${mapped[0].owner}/${mapped[0].name}`)
        }
      }

      if (issuesRes.ok) {
        const issuesData = await issuesRes.json()
        const mapped = issuesData.map((i: any) => ({
          id: i.id,
          repo: i.repository,
          title: i.title,
          number: `#${i.number}`,
          rawNumber: i.number,
          label: i.label,
          age: i.updated_at,
          difficulty: i.difficulty === 'good_first_issue' ? 'Good first issue' : 'Intermediate',
          body: i.body,
          ai_analysis: i.ai_analysis,
          agent_status: i.agent_status,
          sandbox_result: i.sandbox_result,
        }))
        setRealIssues(mapped)
      }

      if (featuresRes.ok) {
        const featuresData = await featuresRes.json()
        setFeatures(featuresData)
      }

      if (runsRes.ok) {
        const runsData = await runsRes.json()
        setRuns(runsData)
        const running = runsData.find((r: any) => r.status === 'running') ?? null
        setActiveRun(running)
      }

      if (prsRes.ok) {
        const prsData = await prsRes.json()
        setPullRequests(prsData)
      }
    } catch (err) {
      console.error('Failed to fetch data:', err)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    fetch('http://localhost:8000/api/health', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Health request failed')
        return response.json() as Promise<OllamaHealth>
      })
      .then(setOllamaHealth)
      .catch(() => {
        if (!controller.signal.aborted) {
          setOllamaHealth({
            ollama_connected: false,
            configured_model: 'qwen3.5:9b',
            model_available: false,
          })
        }
      })

    fetchData()
    const interval = setInterval(fetchData, 10000)

    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [])

  // Fast-poll while a discovery run is active
  useEffect(() => {
    if (!activeRun) return
    const id = setInterval(fetchData, 2000)
    return () => clearInterval(id)
  }, [activeRun?.id])

  const filteredRepos = useMemo(
    () =>
      realRepos.filter((repo) => {
        const matchesQuery = `${repo.name} ${repo.owner} ${repo.description}`
          .toLowerCase()
          .includes(query.toLowerCase())
        return matchesQuery && (!pythonOnly || repo.language === 'Python')
      }),
    [query, pythonOnly, realRepos],
  )

  const filteredFeatures = useMemo(
    () =>
      features.filter((f) => {
        if (featureCategoryFilter === 'all') return true
        return f.category.toLowerCase() === featureCategoryFilter.toLowerCase()
      }),
    [features, featureCategoryFilter],
  )

  async function runDiscovery() {
    if (scanning) return
    setScanning(true)

    try {
      const response = await fetch('http://localhost:8000/api/discovery/trigger', {
        method: 'POST',
      })

      if (response.ok) {
        const data = await response.json()
        console.log('Discovery started:', data)
        setLastScan('Running...')

        setTimeout(() => {
          fetchData()
          setLastScan('Just now')
        }, 5000)
      }
    } catch (err) {
      console.error('Failed to trigger discovery:', err)
    } finally {
      setTimeout(() => setScanning(false), 2000)
    }
  }

  async function suggestFeatures(repoFullName: string) {
    setSuggestingRepo((prev) => ({ ...prev, [repoFullName]: true }))
    try {
      const res = await fetch(
        `http://localhost:8000/api/repositories/${repoFullName}/suggest-features`,
        {
          method: 'POST',
        },
      )
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to suggest features')
      }
      const data = await res.json()
      if (data.suggestions && data.suggestions.length > 0) {
        setFeatures((prev) => {
          const newIds = new Set(data.suggestions.map((s: any) => s.id))
          return [...data.suggestions, ...prev.filter((f) => !newIds.has(f.id))]
        })
        setActiveTab('Feature Ideas')
      }
      fetchData()
    } catch (err: any) {
      alert(`Feature suggestion failed: ${err.message}`)
    } finally {
      setSuggestingRepo((prev) => ({ ...prev, [repoFullName]: false }))
    }
  }

  async function runFeatureSandbox(
    feature: FeatureSuggestion,
    file_rewrites: Record<string, string>,
  ) {
    setFeatureSandboxState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      const res = await fetch(`http://localhost:8000/api/features/${feature.id}/sandbox-verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_full_name: feature.repository,
          file_rewrites: file_rewrites,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Sandbox verification failed')
      }
      const report: SandboxReport = await res.json()
      setFeatureSandboxState((prev) => ({ ...prev, [feature.id]: { loading: false, report } }))
      fetchData()
    } catch (err: any) {
      setFeatureSandboxState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, error: err.message ?? 'Sandbox error' },
      }))
    }
  }

  async function autoHealFeature(
    feature: FeatureSuggestion,
    currentRewrites: Record<string, string>,
    diagnostics: SandboxReport,
  ) {
    setFeatureHealingState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      const res = await fetch('http://localhost:8000/api/sandbox/auto-heal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_full_name: feature.repository,
          title: feature.title,
          file_rewrites: currentRewrites,
          sandbox_diagnostics: diagnostics,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Auto-healing failed')
      }
      const data = await res.json()
      const healedRewrites = data.file_rewrites
      const analysis = data.healing_analysis

      // Update the rewrites in featureImplementState
      setFeatureImplementState((prev) => {
        const existing = prev[feature.id]
        if (!existing?.result) return prev
        return {
          ...prev,
          [feature.id]: {
            ...existing,
            result: {
              ...existing.result,
              file_rewrites: healedRewrites,
            },
          },
        }
      })

      setFeatureHealingState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, analysis },
      }))

      // Automatically re-run sandbox on the healed files
      await runFeatureSandbox(feature, healedRewrites)
    } catch (err: any) {
      alert(`Auto-healing failed: ${err.message}`)
      setFeatureHealingState((prev) => ({ ...prev, [feature.id]: { loading: false } }))
    }
  }

  async function runIssueSandbox(issue: Issue, file_rewrites: Record<string, string>) {
    setIssueSandboxState((prev) => ({ ...prev, [issue.id]: { loading: true } }))
    try {
      const res = await fetch(`http://localhost:8000/api/issues/${issue.id}/sandbox-verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_full_name: issue.repo,
          file_rewrites: file_rewrites,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Sandbox verification failed')
      }
      const report: SandboxReport = await res.json()
      setIssueSandboxState((prev) => ({ ...prev, [issue.id]: { loading: false, report } }))
      fetchData()
    } catch (err: any) {
      setIssueSandboxState((prev) => ({
        ...prev,
        [issue.id]: { loading: false, error: err.message ?? 'Sandbox error' },
      }))
    }
  }

  async function autoHealIssue(
    issue: Issue,
    currentRewrites: Record<string, string>,
    diagnostics: SandboxReport,
  ) {
    setIssueHealingState((prev) => ({ ...prev, [issue.id]: { loading: true } }))
    try {
      const res = await fetch('http://localhost:8000/api/sandbox/auto-heal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_full_name: issue.repo,
          title: issue.title,
          file_rewrites: currentRewrites,
          sandbox_diagnostics: diagnostics,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Auto-healing failed')
      }
      const data = await res.json()
      const healedRewrites = data.file_rewrites
      const analysis = data.healing_analysis

      // Update the rewrites in analyzeState
      setAnalyzeState((prev) => {
        const existing = prev[issue.id]
        if (!existing?.result) return prev
        return {
          ...prev,
          [issue.id]: {
            ...existing,
            result: {
              ...existing.result,
              file_rewrites: healedRewrites,
            },
          },
        }
      })

      setIssueHealingState((prev) => ({
        ...prev,
        [issue.id]: { loading: false, analysis },
      }))

      // Automatically re-run sandbox on the healed files
      await runIssueSandbox(issue, healedRewrites)
    } catch (err: any) {
      alert(`Auto-healing failed: ${err.message}`)
      setIssueHealingState((prev) => ({ ...prev, [issue.id]: { loading: false } }))
    }
  }

  async function implementFeature(feature: FeatureSuggestion) {
    setFeatureImplementState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      const res = await fetch(`http://localhost:8000/api/features/${feature.id}/implement`, {
        method: 'POST',
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Feature implementation failed')
      }
      const result: ImplementFeatureResult = await res.json()
      setFeatureImplementState((prev) => ({ ...prev, [feature.id]: { loading: false, result } }))
      // Automatically trigger sandbox verification for instant feedback
      runFeatureSandbox(feature, result.file_rewrites)
      fetchData()
    } catch (err: any) {
      setFeatureImplementState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, error: err.message ?? 'Unknown error' },
      }))
    }
  }

  async function submitFeaturePR(feature: FeatureSuggestion, result: ImplementFeatureResult) {
    setFeaturePrSubmitting((prev) => ({ ...prev, [feature.id]: true }))
    try {
      const res = await fetch(`http://localhost:8000/api/features/${feature.id}/create-pr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pr_title: result.pr_title,
          pr_body: result.pr_body,
          file_rewrites: result.file_rewrites,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'PR creation failed')
      }
      const pr: PullRequest = await res.json()
      setPullRequests((prev) => [pr, ...prev])
      fetchData()
      setSelectedFeature(null)
    } catch (err: any) {
      alert(`Feature PR creation failed: ${err.message}`)
    } finally {
      setFeaturePrSubmitting((prev) => ({ ...prev, [feature.id]: false }))
    }
  }

  async function analyzeIssue(issue: Issue) {
    setAnalyzeState((prev) => ({ ...prev, [issue.id]: { loading: true } }))
    try {
      const res = await fetch(`http://localhost:8000/api/issues/${issue.id}/analyze`, {
        method: 'POST',
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Analysis failed')
      }
      const result: AnalyzeResult = await res.json()
      setAnalyzeState((prev) => ({ ...prev, [issue.id]: { loading: false, result } }))
      // Automatically trigger sandbox verification
      runIssueSandbox(issue, result.file_rewrites)
      fetchData()
    } catch (err: any) {
      setAnalyzeState((prev) => ({
        ...prev,
        [issue.id]: { loading: false, error: err.message ?? 'Unknown error' },
      }))
    }
  }

  
  async function runDiffReview(issue: Issue, analyzeRes: AnalyzeResult, sandboxRes?: SandboxReport) {
    setReviewState((prev) => ({ ...prev, [issue.id]: { loading: true } }))
    try {
      const res = await fetch(`http://localhost:8000/api/issues/${issue.id}/review-patch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_rewrites: analyzeRes.file_rewrites,
          acceptance_criteria: analyzeRes.acceptance_criteria || [],
          sandbox_result: sandboxRes,
        })
      })
      if (!res.ok) throw new Error('Review failed')
      const result = await res.json()
      setReviewState((prev) => ({ ...prev, [issue.id]: { loading: false, result } }))
    } catch(err: any) {
      setReviewState((prev) => ({ ...prev, [issue.id]: { loading: false } }))
      alert(err.message)
    }
  }

  async function submitPR(issue: Issue, result: AnalyzeResult) {
    setPrSubmitting((prev) => ({ ...prev, [issue.id]: true }))
    try {
      const res = await fetch(`http://localhost:8000/api/issues/${issue.id}/create-pr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pr_title: result.pr_title,
          pr_body: result.pr_body,
          file_rewrites: result.file_rewrites,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'PR creation failed')
      }
      const pr: PullRequest = await res.json()
      setPullRequests((prev) => [pr, ...prev])
      fetchData()
      setSelectedIssue(null)
    } catch (err: any) {
      alert(`PR creation failed: ${err.message}`)
    } finally {
      setPrSubmitting((prev) => ({ ...prev, [issue.id]: false }))
    }
  }

  function getRepoColor(name: string): string {
    const colors = ['#d4f1df', '#f7dbb8', '#d9e5f6', '#f4d4d0', '#d7ead0', '#f3e3b6']
    const index = name.charCodeAt(0) % colors.length
    return colors[index]
  }

  function prStatusClass(status: string) {
    if (status === 'open') return 'good'
    if (status === 'failed') return 'changes'
    return 'review'
  }

  function categoryBadgeClass(category: string) {
    switch (category?.toLowerCase()) {
      case 'optimization':
        return 'badge-opt'
      case 'type_safety':
        return 'badge-type'
      case 'tooling':
        return 'badge-tooling'
      case 'testing':
        return 'badge-testing'
      case 'documentation':
        return 'badge-docs'
      default:
        return 'badge-feat'
    }
  }

  const NavItemWithCount = ({
    label,
    icon: Icon,
    count,
  }: {
    label: string
    icon: any
    count?: number
  }) => (
    <button
      type="button"
      className={`nav-item ${activeTab === label ? 'active' : ''}`}
      onClick={() => setActiveTab(label)}
    >
      <Icon size={17} strokeWidth={1.8} />
      <span>{label}</span>
      {count !== undefined && count > 0 && <span className="nav-count">{count}</span>}
    </button>
  )

  const isOverview = activeTab === 'Overview'
  const showRepos = isOverview || activeTab === 'Repositories'
  const showIssues = isOverview || activeTab === 'Issue queue'
  const showFeatures = activeTab === 'Feature Ideas'

  // Derive analyze state for selected issue / feature
  const selectedAnalyze = selectedIssue ? analyzeState[selectedIssue.id] : undefined
  const selectedFeatureImplement = selectedFeature
    ? featureImplementState[selectedFeature.id]
    : undefined

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" onClick={() => setActiveTab('Overview')}>
          <span className="brand-mark">
            <Code2 size={19} strokeWidth={2.5} />
          </span>
          <span>
            patchwork<span className="brand-period">.</span>
          </span>
        </a>

        <div className="workspace-switcher">
          <span className="workspace-avatar">H</span>
          <span className="workspace-copy">
            <strong>Harsha's workspace</strong>
            <small>Local-first agent</small>
          </span>
          <ChevronDown size={15} />
        </div>

        <div className="side-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          <NavItemWithCount label="Overview" icon={LayoutDashboard} />
          <NavItemWithCount
            label="Repositories"
            icon={Radar}
            count={realRepos.length || undefined}
          />
          <NavItemWithCount
            label="Issue queue"
            icon={ListTodo}
            count={realIssues.length || undefined}
          />
          <NavItemWithCount
            label="Feature Ideas"
            icon={Sparkles}
            count={features.length || undefined}
          />
          <NavItemWithCount label="Runs" icon={Activity} count={runs.length || undefined} />
          <NavItemWithCount
            label="Pull requests"
            icon={GitPullRequest}
            count={pullRequests.length || undefined}
          />
        </nav>

        <div className="side-label side-label-spaced">YOUR SETUP</div>
        <div className="setup-card">
          <div className="setup-heading">
            <span className={`online-dot ${ollamaHealth?.ollama_connected ? '' : 'offline'}`} />{' '}
            {ollamaHealth
              ? ollamaHealth.ollama_connected
                ? 'Ollama connected'
                : 'Ollama unavailable'
              : 'Checking Ollama...'}
          </div>
          <div className="model-name">{ollamaHealth?.configured_model ?? 'qwen3.5:9b'}</div>
          <div className="setup-meta">
            <span>localhost:11434</span>
            <span className="setup-pulse">
              {ollamaHealth?.model_available ? 'MODEL READY' : 'MODEL MISSING'}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="nav-item settings-button"
          onClick={() => setActiveTab('Settings')}
        >
          <Settings2 size={17} strokeWidth={1.8} />
          <span>Settings</span>
        </button>

        <div className="sidebar-bottom">
          <div className="usage-card">
            <div className="usage-title">
              <span>DAILY SCAN</span>
              <span>
                {realRepos.length > 0 ? `${Math.round((realRepos.length / 50) * 100)}%` : '0%'}
              </span>
            </div>
            <div className="usage-track">
              <span style={{ width: `${(realRepos.length / 50) * 100}%` }} />
            </div>
            <p>{realRepos.length} of 50 repositories scanned</p>
          </div>
          <div className="profile-row">
            <span className="profile-avatar">HG</span>
            <span>
              <strong>Harsha G</strong>
              <small>Personal account</small>
            </span>
            <ChevronDown size={14} />
          </div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <span className="crumb-slash">/</span>
            <strong>{activeTab}</strong>
          </div>
          <div className="topbar-actions">
            <span className="topbar-status">
              <span className={`online-dot ${ollamaHealth?.ollama_connected ? '' : 'offline'}`} />{' '}
              {ollamaHealth
                ? ollamaHealth.ollama_connected
                  ? 'Ollama online'
                  : 'Ollama offline'
                : 'Checking local services'}
            </span>
            <button
              className="icon-button notification-button"
              type="button"
              title="Notifications"
              aria-label="Notifications"
            >
              <Bell size={17} />
              <i />
            </button>
            <span className="topbar-divider" />
            <button className="help-button" type="button">
              <span className="help-dot">?</span> Help
            </button>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="eyebrow-line" /> OPEN SOURCE CONTRIBUTION AGENT
              </div>
              <h1>
                Autonomous GitHub <span className="title-break">intelligence.</span>
              </h1>
              <p className="heading-subtitle">
                Scans trending repos daily, resolves reported issues, and proactively proposes
                high-impact architectural enhancements.
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button button-primary"
                type="button"
                onClick={runDiscovery}
                disabled={scanning}
              >
                {scanning ? (
                  <>
                    <Loader size={16} className="spin" /> Scanning...
                  </>
                ) : (
                  <>
                    <Play size={16} /> Run discovery
                  </>
                )}
              </button>
            </div>
          </section>

          {/* Active discovery banner */}
          {activeRun && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.75rem 1.25rem',
                background: '#edf4e8',
                border: '1px solid #cce0c2',
                borderRadius: '8px',
                marginBottom: '1rem',
                fontSize: '0.85rem',
                color: '#2d5a27',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Loader size={16} />
                <span>
                  <strong>Discovery in progress:</strong> Scanning repositories and analyzing
                  issues… ({activeRun.repositories_scanned} scanned, {activeRun.issues_found} issues
                  found)
                </span>
              </div>
              <span style={{ fontSize: '0.78rem', opacity: 0.8 }}>Auto-refreshing</span>
            </div>
          )}

          {isOverview && (
            <section className="metric-grid" aria-label="Today's metrics">
              <article className="metric-card">
                <div className="metric-top">
                  <span>REPOSITORIES SCANNED</span>
                  <Radar size={16} />
                </div>
                <div className="metric-value">
                  {realRepos.length}
                  <span className="metric-total"> / 50</span>
                </div>
                <div className="metric-foot">
                  <span className="metric-up">
                    <ArrowUpRight size={13} /> {realRepos.length} today
                  </span>
                  <span>Daily target</span>
                </div>
                <div className="metric-progress">
                  <span style={{ width: `${(realRepos.length / 50) * 100}%` }} />
                </div>
              </article>
              <article className="metric-card">
                <div className="metric-top">
                  <span>ISSUES WORTH A LOOK</span>
                  <ListTodo size={16} />
                </div>
                <div className="metric-value">{realIssues.length}</div>
                <div className="metric-foot">
                  <span className="metric-highlight">
                    {realIssues.filter((i) => i.difficulty === 'Good first issue').length} good
                    first issues
                  </span>
                  <span>Across {new Set(realIssues.map((i) => i.repo)).size} repos</span>
                </div>
                <div className="metric-sparkline">
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                  <i />
                </div>
              </article>
              <article className="metric-card">
                <div className="metric-top">
                  <span>FEATURE PROPOSALS</span>
                  <Sparkles size={16} />
                </div>
                <div className="metric-value">{features.length}</div>
                <div className="metric-foot">
                  <span className="metric-highlight">
                    {features.filter((f) => f.status === 'suggested').length} ready to implement
                  </span>
                  <span>Proactive contributions</span>
                </div>
                <div className="metric-pr-line">
                  <span className="pr-segment passing" />
                  <span className="pr-segment review" />
                  <span className="pr-segment changes" />
                </div>
              </article>
              <article className="metric-card metric-card-dark">
                <div className="metric-top">
                  <span>LOCAL MODEL</span>
                  <Terminal size={16} />
                </div>
                <div className="model-metric">
                  <span className="model-orbit">
                    <CpuIcon />
                  </span>
                  <span>
                    <strong>{ollamaHealth?.configured_model ?? 'qwen3.5:9b'}</strong>
                    <small>Served locally with Ollama</small>
                  </span>
                </div>
                <div className="metric-foot">
                  <span className="model-live">
                    <span
                      className={`online-dot ${ollamaHealth?.model_available ? '' : 'offline'}`}
                    />{' '}
                    {ollamaHealth?.model_available ? 'Model ready' : 'Not available'}
                  </span>
                  <span>Private by default</span>
                </div>
              </article>
            </section>
          )}

          {/* Repositories & Issue Queue Views */}
          <div className={`content-grid ${!isOverview ? 'content-grid-single' : ''}`}>
            {showRepos && (
              <section className="panel repo-panel">
                <div className="panel-header">
                  <div>
                    <div className="section-kicker">DISCOVERY FEED</div>
                    <h2>
                      {activeTab === 'Repositories' ? 'Repositories' : 'Trending repositories'}{' '}
                      <span className="heading-count">{filteredRepos.length}</span>
                    </h2>
                  </div>
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => setActiveTab('Repositories')}
                  >
                    View all <ArrowRight size={14} />
                  </button>
                </div>
                <div className="repo-toolbar">
                  <label className="search-field">
                    <Search size={15} />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Search repositories"
                      aria-label="Search repositories"
                    />
                    {query && (
                      <button aria-label="Clear search" type="button" onClick={() => setQuery('')}>
                        <X size={13} />
                      </button>
                    )}
                  </label>
                  <button
                    type="button"
                    className={`filter-button ${pythonOnly ? 'filter-active' : ''}`}
                    onClick={() => setPythonOnly(!pythonOnly)}
                  >
                    <SlidersHorizontal size={13} />
                    <span>Python only</span>
                  </button>
                </div>
                <div className="repo-table-wrap">
                  <table className="repo-table">
                    <thead>
                      <tr>
                        <th>REPOSITORY</th>
                        <th>TRACTION</th>
                        <th>ISSUES</th>
                        <th>FIT SCORE</th>
                        <th>ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRepos.slice(0, isOverview ? 5 : 50).map((repo) => (
                        <tr key={repo.name}>
                          <td>
                            <div className="repo-name-cell">
                              <span className="repo-avatar" style={{ background: repo.color }}>
                                {repo.initials}
                              </span>
                              <span className="repo-info">
                                <strong>
                                  {repo.owner}
                                  <b>/</b>
                                  {repo.name}
                                </strong>
                                <small>{repo.description}</small>
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className="stars-cell">
                              <Star size={13} /> {repo.stars}
                            </span>
                            <span className="trend-cell">
                              <Flame size={11} /> {repo.trend}
                            </span>
                          </td>
                          <td>
                            <span className="issue-total">{repo.issues}</span>
                            <span className="language-dot" />
                            {repo.language}
                          </td>
                          <td>
                            <div className="score-cell">
                              <span className="score-track">
                                <i style={{ width: `${repo.score}%` }} />
                              </span>
                              <strong>{repo.score}</strong>
                            </div>
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <button
                                className="suggest-btn"
                                type="button"
                                disabled={suggestingRepo[`${repo.owner}/${repo.name}`]}
                                onClick={() => suggestFeatures(`${repo.owner}/${repo.name}`)}
                                title="Analyze repo structure and propose features"
                              >
                                {suggestingRepo[`${repo.owner}/${repo.name}`] ? (
                                  <>
                                    <Loader size={11} className="spin" /> Proposing...
                                  </>
                                ) : (
                                  <>
                                    <Sparkles size={11} /> Suggest Ideas
                                  </>
                                )}
                              </button>
                              <a
                                href={`https://github.com/${repo.owner}/${repo.name}`}
                                target="_blank"
                                rel="noreferrer"
                                className="row-action"
                                title={`Open ${repo.name} on GitHub`}
                                aria-label={`Open ${repo.name}`}
                              >
                                <ArrowUpRight size={15} />
                              </a>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {filteredRepos.length === 0 && (
                        <tr>
                          <td colSpan={5} className="empty-state">
                            No repositories match this search.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="panel-footer">
                  <span>Showing {filteredRepos.length} of 50 discovered today</span>
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => setActiveTab('Repositories')}
                  >
                    Browse discovery <ArrowRight size={14} />
                  </button>
                </div>
              </section>
            )}

            {showIssues && (
              <section className="panel issue-panel">
                <div className="panel-header">
                  <div>
                    <div className="section-kicker">CURATED FOR YOU</div>
                    <h2>
                      Issue queue{' '}
                      <span className="heading-count heading-count-warm">
                        {realIssues.length.toString().padStart(2, '0')}
                      </span>
                    </h2>
                  </div>
                  <button
                    className="icon-button panel-more"
                    type="button"
                    title="Issue filters"
                    aria-label="Issue filters"
                  >
                    <Settings2 size={16} />
                  </button>
                </div>
                <div className="issue-list">
                  {realIssues.length > 0 ? (
                    realIssues
                      .slice(0, isOverview ? 3 : realIssues.length)
                      .map((issue) => (
                        <article className="issue-item" key={issue.number}>
                          <div className="issue-item-top">
                            <span
                              className={`difficulty ${issue.difficulty === 'Good first issue' ? 'difficulty-good' : 'difficulty-mid'}`}
                            >
                              <span />
                              {issue.difficulty}
                            </span>
                            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                              {issue.agent_status === 'analyzing' ? (
                                <span
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.3rem',
                                    fontSize: '0.72rem',
                                    color: '#5b8256',
                                  }}
                                >
                                  <Loader size={11} /> Analyzing…
                                </span>
                              ) : issue.agent_status === 'analyzed' ? (
                                <span
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.25rem',
                                    fontSize: '0.72rem',
                                    color: '#2e7d32',
                                    fontWeight: 600,
                                  }}
                                >
                                  <CircleCheck size={11} /> Patch ready
                                </span>
                              ) : issue.agent_status === 'pr_created' ? (
                                <span
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.25rem',
                                    fontSize: '0.72rem',
                                    color: '#1565c0',
                                    fontWeight: 600,
                                  }}
                                >
                                  <GitPullRequest size={11} /> PR Created
                                </span>
                              ) : null}
                              <button
                                className="icon-button issue-open"
                                type="button"
                                title={`Inspect ${issue.number}`}
                                aria-label={`Inspect ${issue.number}`}
                                onClick={() => setSelectedIssue(issue)}
                              >
                                <ArrowUpRight size={14} />
                              </button>
                            </div>
                          </div>
                          <button
                            className="issue-title"
                            type="button"
                            onClick={() => setSelectedIssue(issue)}
                          >
                            {issue.title}
                          </button>
                          <div className="issue-meta">
                            <span>{issue.repo}</span>
                            <span className="meta-dot">·</span>
                            <span>{issue.number}</span>
                          </div>
                          <div className="issue-bottom">
                            <span className="issue-label">{issue.label}</span>
                            <span className="issue-age">
                              <Clock3 size={11} /> {issue.age}
                            </span>
                          </div>
                        </article>
                      ))
                  ) : (
                    <div
                      style={{
                        padding: '3rem 2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <p style={{ marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 500 }}>
                        No issues discovered yet
                      </p>
                      <p style={{ fontSize: '0.85rem', opacity: 0.7 }}>
                        Run discovery to find contribution opportunities
                      </p>
                    </div>
                  )}
                </div>
                {realIssues.length > 0 && (
                  <button
                    className="queue-link"
                    type="button"
                    onClick={() => setActiveTab('Issue queue')}
                  >
                    Open full issue queue <ArrowRight size={14} />
                  </button>
                )}
              </section>
            )}
          </div>

          {/* Feature Ideas Tab */}
          {showFeatures && (
            <section className="panel feature-panel">
              <div className="panel-header" style={{ flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div className="section-kicker">PROACTIVE CONTRIBUTIONS</div>
                  <h2>
                    AI Feature Proposals{' '}
                    <span className="heading-count heading-count-warm">
                      {filteredFeatures.length.toString().padStart(2, '0')}
                    </span>
                  </h2>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <select
                    className="repo-select"
                    value={quickSuggestRepo}
                    onChange={(e) => setQuickSuggestRepo(e.target.value)}
                    style={{
                      padding: '5px 10px',
                      borderRadius: '5px',
                      border: '1px solid #d2ded5',
                      fontSize: '10px',
                      fontFamily: 'inherit',
                      background: '#fff',
                      color: '#234239',
                    }}
                  >
                    {realRepos.map((r) => (
                      <option key={`${r.owner}/${r.name}`} value={`${r.owner}/${r.name}`}>
                        {r.owner}/{r.name}
                      </option>
                    ))}
                  </select>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={!quickSuggestRepo || suggestingRepo[quickSuggestRepo]}
                    onClick={() => quickSuggestRepo && suggestFeatures(quickSuggestRepo)}
                    style={{ padding: '6px 12px', fontSize: '10px' }}
                  >
                    {quickSuggestRepo && suggestingRepo[quickSuggestRepo] ? (
                      <>
                        <Loader size={12} className="spin" /> Proposing...
                      </>
                    ) : (
                      <>
                        <Wand2 size={12} /> Propose Features
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Filter pills */}
              <div className="feature-filter-bar">
                {[
                  { id: 'all', label: 'All Ideas' },
                  { id: 'feature', label: 'New Features' },
                  { id: 'optimization', label: 'Performance' },
                  { id: 'type_safety', label: 'Type Safety' },
                  { id: 'tooling', label: 'Tooling & CI' },
                  { id: 'testing', label: 'Testing' },
                  { id: 'documentation', label: 'Docs' },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={`feature-filter-btn ${featureCategoryFilter === f.id ? 'active' : ''}`}
                    onClick={() => setFeatureCategoryFilter(f.id)}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              {/* Feature Cards Grid */}
              <div className="feature-grid">
                {filteredFeatures.length > 0 ? (
                  filteredFeatures.map((f) => (
                    <article className="feature-card" key={f.id}>
                      <div>
                        <div className="feature-card-header">
                          <span
                            className={`feature-category-badge ${categoryBadgeClass(f.category)}`}
                          >
                            {f.category.replace('_', ' ')}
                          </span>
                          <span className="feature-impact-badge">
                            <Sparkles size={10} /> Impact {f.impact_score}/100
                          </span>
                        </div>
                        <h3 className="feature-title" onClick={() => setSelectedFeature(f)}>
                          {f.title}
                        </h3>
                        <div className="feature-repo-link">{f.repository}</div>
                        <p className="feature-desc">{f.description}</p>
                      </div>

                      <div>
                        {f.suggested_files && f.suggested_files.length > 0 && (
                          <div className="feature-files-row">
                            {f.suggested_files.slice(0, 2).map((file, idx) => (
                              <span className="feature-file-chip" key={idx} title={file}>
                                {file.split('/').pop()}
                              </span>
                            ))}
                            {f.suggested_files.length > 2 && (
                              <span className="feature-file-chip">
                                +{f.suggested_files.length - 2} more
                              </span>
                            )}
                          </div>
                        )}

                        <div className="feature-card-footer">
                          <span className={`feature-status-pill status-${f.status}`}>
                            {f.status === 'suggested'
                              ? 'Ready to Implement'
                              : f.status === 'implementing'
                              ? 'Implementing...'
                              : f.status === 'implemented'
                              ? 'Code Generated'
                              : f.status === 'pr_created'
                              ? 'PR Created'
                              : f.status}
                          </span>
                          <button
                            className="button button-quiet"
                            type="button"
                            onClick={() => setSelectedFeature(f)}
                            style={{ padding: '4px 10px', fontSize: '9px' }}
                          >
                            Inspect & Implement <ArrowRight size={11} />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  <div
                    style={{
                      gridColumn: '1 / -1',
                      padding: '4rem 2rem',
                      textAlign: 'center',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    <Sparkles
                      size={28}
                      style={{ margin: '0 auto 0.8rem', opacity: 0.5, color: '#446b46' }}
                    />
                    <p style={{ marginBottom: '0.5rem', fontSize: '0.95rem', fontWeight: 600 }}>
                      No feature proposals in this category yet
                    </p>
                    <p style={{ fontSize: '0.85rem', opacity: 0.7, maxWidth: '400px', margin: '0 auto' }}>
                      Click "Suggest Ideas" on any repository in the discovery feed or select a repo
                      above to generate architectural proposals.
                    </p>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Pull requests panel */}
          {(isOverview || activeTab === 'Pull requests') && pullRequests.length > 0 && (
            <section className="panel activity-panel">
              <div className="panel-header activity-header">
                <div>
                  <div className="section-kicker">CONTRIBUTION TRACKER</div>
                  <h2>
                    Pull request activity{' '}
                    <span className="heading-count">
                      {pullRequests.length.toString().padStart(2, '0')}
                    </span>
                  </h2>
                </div>
                <div className="activity-header-actions">
                  <span className="updated-label">
                    <span className="online-dot" /> Synced {lastScan.toLowerCase()}
                  </span>
                  <button
                    className="text-action"
                    type="button"
                    onClick={() => setActiveTab('Pull requests')}
                  >
                    All pull requests <ArrowRight size={14} />
                  </button>
                </div>
              </div>
              <div className="pr-table-wrap">
                <table className="pr-table">
                  <thead>
                    <tr>
                      <th>CONTRIBUTION</th>
                      <th>STATUS</th>
                      <th>CREATED</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {pullRequests.map((pr) => (
                      <tr key={pr.id}>
                        <td>
                          <span className="pr-icon">
                            <GitPullRequest size={15} />
                          </span>
                          <span className="pr-name">
                            <strong>{pr.title}</strong>
                            <small>
                              {pr.repository} <span>·</span>{' '}
                              {pr.number ? `#${pr.number}` : 'pending'}
                            </small>
                          </span>
                        </td>
                        <td>
                          <span className={`pr-status status-${prStatusClass(pr.status)}`}>
                            <span />
                            {pr.status}
                          </span>
                        </td>
                        <td className="pr-updated">{pr.created_at}</td>
                        <td>
                          {pr.url ? (
                            <a
                              href={pr.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="row-action"
                              title="Open pull request"
                              aria-label={`Open pull request ${pr.number}`}
                            >
                              <ExternalLink size={14} />
                            </a>
                          ) : (
                            <button
                              className="row-action"
                              type="button"
                              title="Inspect pull request"
                              aria-label={`Inspect pull request ${pr.number}`}
                            >
                              <ArrowUpRight size={15} />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Empty pull requests tab */}
          {activeTab === 'Pull requests' && pullRequests.length === 0 && (
            <section className="panel activity-panel">
              <div className="panel-header">
                <div>
                  <div className="section-kicker">CONTRIBUTION TRACKER</div>
                  <h2>Pull requests</h2>
                </div>
              </div>
              <div
                style={{
                  padding: '3rem 2rem',
                  textAlign: 'center',
                  color: 'var(--text-secondary)',
                }}
              >
                <p style={{ marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: 500 }}>
                  No pull requests yet
                </p>
                <p style={{ fontSize: '0.85rem', opacity: 0.7 }}>
                  Analyze an issue or implement a proposed feature to open a PR
                </p>
              </div>
            </section>
          )}

          
          {activeTab === 'Metrics' && (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <div className="section-kicker">TELEMETRY</div>
                  <h2>Contribution Metrics</h2>
                  <p className="panel-meta">Measuring the impact and efficiency of AI open-source contributions.</p>
                </div>
              </div>
              <div className="panel-body">
                {telemetry?.metrics ? (
                  <div className="stats-grid">
                    <div className="stat-card">
                      <div className="stat-label">Issue selection precision</div>
                      <div className="stat-value">{telemetry.metrics.issue_selection_precision}</div>
                      <div className="stat-desc">Suitable vs total selected</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-label">First-pass test success</div>
                      <div className="stat-value">{telemetry.metrics.first_pass_test_success}</div>
                      <div className="stat-desc">Zero AI repair attempts needed</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-label">Repair success rate</div>
                      <div className="stat-value">{telemetry.metrics.repair_success_rate}</div>
                      <div className="stat-desc">Self-healing loop effectiveness</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-label">Merge rate</div>
                      <div className="stat-value">{telemetry.metrics.merge_rate}</div>
                      <div className="stat-desc">PRs accepted by maintainers</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-label">Duplicate PR rate</div>
                      <div className="stat-value">{telemetry.metrics.duplicate_pr_rate}</div>
                      <div className="stat-desc">Blocked by pre-flight checks</div>
                    </div>
                    <div className="stat-card">
                      <div className="stat-label">Cost per contribution</div>
                      <div className="stat-value">{telemetry.metrics.cost_per_contribution}</div>
                      <div className="stat-desc">Local token compute equiv.</div>
                    </div>
                  </div>
                ) : (
                  <div className="empty-state">
                    Loading metrics...
                  </div>
                )}
              </div>
            </section>
          )}

          {activeTab === 'Runs' && (
            <section className="panel runs-panel">
              <div className="panel-header">
                <div>
                  <div className="section-kicker">AUTOMATION HISTORY</div>
                  <h2>Recent runs</h2>
                </div>
                <button className="button button-quiet" type="button" onClick={runDiscovery}>
                  <RefreshCw size={14} /> Run again
                </button>
              </div>
              <div className="run-list">
                {runs.length > 0 ? (
                  runs.map((run) => (
                    <div key={run.id}>
                      <span
                        className={`run-icon ${run.status === 'completed' ? 'run-complete' : 'run-review'}`}
                      >
                        {run.status === 'completed' ? (
                          <CircleCheck size={16} />
                        ) : (
                          <CircleDot size={16} />
                        )}
                      </span>
                      <span>
                        <strong>{run.name}</strong>
                        <small>{run.summary || 'In progress...'}</small>
                      </span>
                      <b>
                        {run.status === 'completed'
                          ? 'Completed'
                          : run.status === 'failed'
                          ? 'Failed'
                          : 'Running'}{' '}
                        <small>{run.created_at}</small>
                      </b>
                    </div>
                  ))
                ) : (
                  <div
                    style={{
                      padding: '2rem',
                      textAlign: 'center',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    No runs yet. Click "Run discovery" to start.
                  </div>
                )}
              </div>
            </section>
          )}

          {activeTab === 'Settings' && (
            <section className="panel settings-panel">
              <div className="panel-header">
                <div>
                  <div className="section-kicker">PREFERENCES</div>
                  <h2>Workspace settings</h2>
                </div>
              </div>
              <div className="settings-row">
                <span>
                  <strong>Repository language</strong>
                  <small>Only include repositories written primarily in Python</small>
                </span>
                <button
                  className={`toggle ${pythonOnly ? 'toggle-on' : ''}`}
                  type="button"
                  aria-label="Toggle Python-only filter"
                  aria-pressed={pythonOnly}
                  onClick={() => setPythonOnly(!pythonOnly)}
                >
                  <span />
                </button>
              </div>
              <div className="settings-row">
                <span>
                  <strong>Daily discovery target</strong>
                  <small>Maximum repositories to scan each day</small>
                </span>
                <span className="setting-value">
                  50 <ChevronDown size={14} />
                </span>
              </div>
              <div className="settings-row">
                <span>
                  <strong>Schedule</strong>
                  <small>Local time for the daily discovery run</small>
                </span>
                <span className="setting-value">
                  09:00 IST <ChevronDown size={14} />
                </span>
              </div>
              <div className="settings-row">
                <span>
                  <strong>Coding model</strong>
                  <small>Local model served through Ollama</small>
                </span>
                <span className="setting-value">
                  {ollamaHealth?.configured_model ?? 'qwen3.5:9b'} <ChevronDown size={14} />
                </span>
              </div>
            </section>
          )}

          <footer className="page-footer">
            <span>
              <span className="footer-mark">p.</span> Built for the long game.
            </span>
            <span>
              Discovery runs daily at 09:00 IST <span className="footer-separator">·</span>{' '}
              <button type="button" onClick={() => setActiveTab('Settings')}>
                Configure schedule
              </button>
            </span>
          </footer>
        </div>
      </main>

      {/* Feature Modal */}
      {selectedFeature && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setSelectedFeature(null)}
        >
          <section
            className="issue-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-feature-title"
            style={{ maxWidth: '720px', width: '92vw' }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-topline">
              <span className="section-kicker">PROACTIVE FEATURE PROPOSAL</span>
              <button
                className="icon-button"
                type="button"
                aria-label="Close feature preview"
                onClick={() => setSelectedFeature(null)}
              >
                <X size={17} />
              </button>
            </div>

            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '8px' }}>
              <span
                className={`feature-category-badge ${categoryBadgeClass(selectedFeature.category)}`}
              >
                {selectedFeature.category.replace('_', ' ')}
              </span>
              <span className="feature-impact-badge">
                <Sparkles size={11} /> Impact Score: {selectedFeature.impact_score}/100
              </span>
              <span
                style={{
                  fontSize: '8px',
                  fontWeight: 600,
                  padding: '3px 6px',
                  borderRadius: '3px',
                  background: '#f2f3ef',
                  color: '#49584e',
                }}
              >
                Complexity: {selectedFeature.complexity}
              </span>
            </div>

            <h2 id="modal-feature-title" style={{ fontSize: '20px', marginTop: '4px' }}>
              {selectedFeature.title}
            </h2>
            <p className="modal-repo">{selectedFeature.repository}</p>

            {/* Description & Motivation */}
            <div
              style={{
                margin: '0.75rem 0',
                padding: '0.85rem 1rem',
                background: 'var(--surface-raised, #f7f7f5)',
                borderRadius: '8px',
                fontSize: '0.82rem',
                color: 'var(--text-primary)',
                lineHeight: 1.55,
              }}
            >
              <strong
                style={{
                  display: 'block',
                  marginBottom: '0.35rem',
                  fontSize: '0.74rem',
                  letterSpacing: '0.04em',
                  color: '#4d6353',
                }}
              >
                MOTIVATION & ARCHITECTURAL VALUE
              </strong>
              {selectedFeature.description}
            </div>

            {/* Implementation Plan */}
            {selectedFeature.implementation_plan && (
              <div
                style={{
                  margin: '0.75rem 0',
                  padding: '0.85rem 1rem',
                  background: '#fcfaf6',
                  border: '1px solid #ebd8be',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: '#433d32',
                  lineHeight: 1.55,
                }}
              >
                <strong
                  style={{
                    display: 'block',
                    marginBottom: '0.35rem',
                    fontSize: '0.74rem',
                    letterSpacing: '0.04em',
                    color: '#916327',
                  }}
                >
                  STEP-BY-STEP IMPLEMENTATION PLAN
                </strong>
                <div style={{ whiteSpace: 'pre-wrap' }}>{selectedFeature.implementation_plan}</div>
              </div>
            )}

            {/* Target Files */}
            {selectedFeature.suggested_files && selectedFeature.suggested_files.length > 0 && (
              <div style={{ margin: '0.75rem 0' }}>
                <span
                  style={{
                    display: 'block',
                    fontSize: '0.72rem',
                    letterSpacing: '0.04em',
                    opacity: 0.65,
                    marginBottom: '0.35rem',
                  }}
                >
                  TARGET FILES ({selectedFeature.suggested_files.length})
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  {selectedFeature.suggested_files.map((file, idx) => (
                    <span className="feature-file-chip" key={idx}>
                      {file}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* AI Code generation state */}
            {!selectedFeatureImplement?.result && (
              <div className="modal-insight">
                <Sparkles size={16} />
                <span>
                  <strong>Ready to implement</strong>
                  <small>
                    Ollama will read the target files in {selectedFeature.repository} and synthesize
                    clean, tested code rewrites.
                  </small>
                </span>
              </div>
            )}

            {selectedFeatureImplement?.loading && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '1rem',
                  fontSize: '0.85rem',
                  color: 'var(--text-secondary)',
                  background: '#f4f8f1',
                  borderRadius: '8px',
                  margin: '0.75rem 0',
                }}
              >
                <Loader size={16} className="spin" />
                <span>
                  Synthesizing feature code with local Qwen model… this may take 30-60 seconds.
                </span>
              </div>
            )}

            {selectedFeatureImplement?.error && (
              <div
                style={{
                  padding: '0.75rem 1rem',
                  background: '#fdecea',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: '#c0392b',
                  marginTop: '0.5rem',
                }}
              >
                {selectedFeatureImplement.error}
              </div>
            )}

            {/* Implementation Results */}
            {selectedFeatureImplement?.result && (
              <div style={{ marginTop: '0.75rem' }}>
                {/* Analysis text */}
                <div
                  style={{
                    padding: '0.75rem 1rem',
                    background: 'var(--surface-raised, #f7f7f5)',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    color: 'var(--text-primary)',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                    marginBottom: '0.75rem',
                  }}
                >
                  <strong
                    style={{
                      display: 'block',
                      marginBottom: '0.4rem',
                      fontSize: '0.75rem',
                      letterSpacing: '0.04em',
                      opacity: 0.6,
                    }}
                  >
                    AI IMPLEMENTATION RATIONALE
                  </strong>
                  {selectedFeatureImplement.result.analysis}
                </div>

                {/* PR Title */}
                <div
                  style={{
                    padding: '0.6rem 1rem',
                    background: '#eef7f2',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    marginBottom: '0.75rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <GitPullRequest size={14} style={{ flexShrink: 0 }} />
                  <span>
                    <strong>PR Title:</strong> {selectedFeatureImplement.result.pr_title}
                  </span>
                </div>

                {/* File rewrites */}
                {Object.keys(selectedFeatureImplement.result.file_rewrites).length > 0 && (
                  <div style={{ marginBottom: '0.75rem' }}>
                    <div
                      style={{
                        fontSize: '0.73rem',
                        letterSpacing: '0.04em',
                        opacity: 0.6,
                        marginBottom: '0.4rem',
                      }}
                    >
                      SYNTHESIZED CODE DIFFS (
                      {Object.keys(selectedFeatureImplement.result.file_rewrites).length})
                    </div>
                    {Object.entries(selectedFeatureImplement.result.file_rewrites).map(
                      ([path, content]) => (
                        <div
                          key={path}
                          style={{
                            border: '1px solid var(--border, #e8e8e4)',
                            borderRadius: '8px',
                            marginBottom: '0.4rem',
                            overflow: 'hidden',
                            fontSize: '0.8rem',
                          }}
                        >
                          <button
                            type="button"
                            style={{
                              width: '100%',
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              padding: '0.5rem 0.75rem',
                              background: '#f0f0ec',
                              border: 'none',
                              cursor: 'pointer',
                              fontFamily: 'monospace',
                              fontSize: '0.78rem',
                            }}
                            onClick={() => setExpandedFile(expandedFile === path ? null : path)}
                          >
                            <span>{path}</span>
                            <ChevronDown
                              size={13}
                              style={{
                                transform: expandedFile === path ? 'rotate(180deg)' : undefined,
                                transition: 'transform 0.15s',
                              }}
                            />
                          </button>
                          {expandedFile === path && (
                            <pre
                              style={{
                                margin: 0,
                                padding: '0.75rem',
                                background: '#1e1e1e',
                                color: '#d4d4d4',
                                fontSize: '0.73rem',
                                overflowX: 'auto',
                                maxHeight: '16rem',
                                overflowY: 'auto',
                                lineHeight: 1.5,
                              }}
                            >
                              {content}
                            </pre>
                          )}
                        </div>
                      ),
                    )}
                  </div>
                )}

                {/* Isolated Test Sandbox Verification Panel */}
                <SandboxPanel
                  repoFullName={selectedFeature.repository}
                  title={selectedFeature.title}
                  fileRewrites={selectedFeatureImplement.result.file_rewrites}
                  sandboxState={
                    featureSandboxState[selectedFeature.id] ||
                    (selectedFeature.sandbox_result
                      ? { loading: false, report: selectedFeature.sandbox_result }
                      : undefined)
                  }
                  healingState={featureHealingState[selectedFeature.id]}
                  activeSubTab={featureSandboxTab}
                  setActiveSubTab={setFeatureSandboxTab}
                  onRunSandbox={() =>
                    runFeatureSandbox(
                      selectedFeature,
                      selectedFeatureImplement.result!.file_rewrites,
                    )
                  }
                  onAutoHeal={(report) =>
                    autoHealFeature(
                      selectedFeature,
                      selectedFeatureImplement.result!.file_rewrites,
                      report,
                    )
                  }
                />
              </div>
            )}

            <div className="modal-actions">
              <button
                className="button button-quiet"
                type="button"
                onClick={() => setSelectedFeature(null)}
              >
                Back to ideas
              </button>

              {!selectedFeatureImplement?.result ? (
                <button
                  className="button button-primary"
                  type="button"
                  disabled={selectedFeatureImplement?.loading}
                  onClick={() => implementFeature(selectedFeature)}
                >
                  {selectedFeatureImplement?.loading ? (
                    <>
                      <Loader size={15} className="spin" /> Implementing…
                    </>
                  ) : (
                    <>
                      <Sparkles size={15} /> Implement with Ollama
                    </>
                  )}
                </button>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {featureSandboxState[selectedFeature.id]?.report?.overall_status === 'passed' && (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 650,
                        color: '#15803d',
                        background: '#dcfce7',
                        padding: '4px 8px',
                        borderRadius: '4px',
                      }}
                    >
                      <CheckCircle2 size={13} /> 100% Sandbox Verified
                    </span>
                  )}
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={
                      featurePrSubmitting[selectedFeature.id] ||
                      Object.keys(selectedFeatureImplement.result.file_rewrites).length === 0
                    }
                    onClick={() =>
                      submitFeaturePR(selectedFeature, selectedFeatureImplement.result!)
                    }
                  >
                    {featurePrSubmitting[selectedFeature.id] ? (
                      <>
                        <Loader size={15} className="spin" /> Creating PR…
                      </>
                    ) : (
                      <>
                        <Plus size={15} /> Create Pull Request
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* Issue modal */}
      {selectedIssue && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setSelectedIssue(null)}
        >
          <section
            className="issue-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            style={{ maxWidth: '680px', width: '92vw' }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-topline">
              <span className="section-kicker">ISSUE PREVIEW</span>
              <button
                className="icon-button"
                type="button"
                aria-label="Close issue preview"
                onClick={() => setSelectedIssue(null)}
              >
                <X size={17} />
              </button>
            </div>

            <span
              className={`difficulty ${selectedIssue.difficulty === 'Good first issue' ? 'difficulty-good' : 'difficulty-mid'}`}
            >
              <span />
              {selectedIssue.difficulty}
            </span>

            <h2 id="modal-title">{selectedIssue.title}</h2>
            <p className="modal-repo">
              {selectedIssue.repo} <span>·</span> {selectedIssue.number}
            </p>

            {/* Issue body */}
            {selectedIssue.body && (
              <div
                style={{
                  margin: '0.75rem 0',
                  padding: '0.75rem 1rem',
                  background: 'var(--surface-raised, #f7f7f5)',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: 'var(--text-secondary)',
                  whiteSpace: 'pre-wrap',
                  maxHeight: '8rem',
                  overflowY: 'auto',
                  lineHeight: 1.55,
                }}
              >
                {selectedIssue.body}
              </div>
            )}

            {/* Analyze section */}
            {!selectedAnalyze?.result && (
              <div className="modal-insight">
                <Sparkles size={16} />
                <span>
                  <strong>Ready to analyze</strong>
                  <small>
                    Let Ollama read the codebase and propose a fix for this issue.
                  </small>
                </span>
              </div>
            )}

            {selectedAnalyze?.loading && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '1rem',
                  fontSize: '0.85rem',
                  color: 'var(--text-secondary)',
                }}
              >
                <Loader size={16} className="spin" />
                Cloning repo and running Ollama analysis… this may take a minute.
              </div>
            )}

            {selectedAnalyze?.error && (
              <div
                style={{
                  padding: '0.75rem 1rem',
                  background: '#fdecea',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  color: '#c0392b',
                  marginTop: '0.5rem',
                }}
              >
                {selectedAnalyze.error}
              </div>
            )}

            {selectedAnalyze?.result && (
              <div style={{ marginTop: '0.75rem' }}>
                {/* Analysis text */}
                <div
                  style={{
                    padding: '0.75rem 1rem',
                    background: 'var(--surface-raised, #f7f7f5)',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    color: 'var(--text-primary)',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                    marginBottom: '0.75rem',
                  }}
                >
                  <strong
                    style={{
                      display: 'block',
                      marginBottom: '0.4rem',
                      fontSize: '0.75rem',
                      letterSpacing: '0.04em',
                      opacity: 0.6,
                    }}
                  >
                    AI ANALYSIS
                  </strong>
                  {selectedAnalyze.result.analysis}
                </div>

                {/* PR title */}
                <div
                  style={{
                    padding: '0.6rem 1rem',
                    background: '#eef7f2',
                    borderRadius: '8px',
                    fontSize: '0.82rem',
                    marginBottom: '0.75rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <GitPullRequest size={14} style={{ flexShrink: 0 }} />
                  <span>
                    <strong>PR Title:</strong> {selectedAnalyze.result.pr_title}
                  </span>
                </div>

                {/* File rewrites */}
                {Object.keys(selectedAnalyze.result.file_rewrites).length > 0 && (
                  <div style={{ marginBottom: '0.75rem' }}>
                    <div
                      style={{
                        fontSize: '0.73rem',
                        letterSpacing: '0.04em',
                        opacity: 0.6,
                        marginBottom: '0.4rem',
                      }}
                    >
                      CHANGED FILES ({Object.keys(selectedAnalyze.result.file_rewrites).length})
                    </div>
                    {Object.entries(selectedAnalyze.result.file_rewrites).map(([path, content]) => (
                      <div
                        key={path}
                        style={{
                          border: '1px solid var(--border, #e8e8e4)',
                          borderRadius: '8px',
                          marginBottom: '0.4rem',
                          overflow: 'hidden',
                          fontSize: '0.8rem',
                        }}
                      >
                        <button
                          type="button"
                          style={{
                            width: '100%',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '0.5rem 0.75rem',
                            background: '#f0f0ec',
                            border: 'none',
                            cursor: 'pointer',
                            fontFamily: 'monospace',
                            fontSize: '0.78rem',
                          }}
                          onClick={() => setExpandedFile(expandedFile === path ? null : path)}
                        >
                          <span>{path}</span>
                          <ChevronDown
                            size={13}
                            style={{
                              transform: expandedFile === path ? 'rotate(180deg)' : undefined,
                              transition: 'transform 0.15s',
                            }}
                          />
                        </button>
                        {expandedFile === path && (
                          <pre
                            style={{
                              margin: 0,
                              padding: '0.75rem',
                              background: '#1e1e1e',
                              color: '#d4d4d4',
                              fontSize: '0.73rem',
                              overflowX: 'auto',
                              maxHeight: '16rem',
                              overflowY: 'auto',
                              lineHeight: 1.5,
                            }}
                          >
                            {content}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Isolated Test Sandbox Verification Panel */}
                <SandboxPanel
                  repoFullName={selectedIssue.repo}
                  title={selectedIssue.title}
                  fileRewrites={selectedAnalyze.result.file_rewrites}
                  sandboxState={
                    issueSandboxState[selectedIssue.id] ||
                    (selectedIssue.sandbox_result
                      ? { loading: false, report: selectedIssue.sandbox_result }
                      : undefined)
                  }
                  healingState={issueHealingState[selectedIssue.id]}
                  activeSubTab={issueSandboxTab}
                  setActiveSubTab={setIssueSandboxTab}
                  onRunSandbox={() =>
                    runIssueSandbox(
                      selectedIssue,
                      selectedAnalyze.result!.file_rewrites,
                    )
                  }
                  onAutoHeal={(report) =>
                    autoHealIssue(
                      selectedIssue,
                      selectedAnalyze.result!.file_rewrites,
                      report,
                    )
                  }
                />
              </div>
            )}

            <div className="modal-actions">
              <button
                className="button button-quiet"
                type="button"
                onClick={() => setSelectedIssue(null)}
              >
                Back to queue
              </button>

              {!selectedAnalyze?.result ? (
                <button
                  className="button button-primary"
                  type="button"
                  disabled={selectedAnalyze?.loading}
                  onClick={() => analyzeIssue(selectedIssue)}
                >
                  {selectedAnalyze?.loading ? (
                    <>
                      <Loader size={15} className="spin" /> Analyzing…
                    </>
                  ) : (
                    <>
                      <Sparkles size={15} /> Analyze with Ollama
                    </>
                  )}
                </button>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {issueSandboxState[selectedIssue.id]?.report?.overall_status === 'passed' && (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 650,
                        color: '#15803d',
                        background: '#dcfce7',
                        padding: '4px 8px',
                        borderRadius: '4px',
                      }}
                    >
                      <CheckCircle2 size={13} /> 100% Sandbox Verified
                    </span>
                  )}
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={
                      reviewState[selectedIssue.id]?.loading ||
                      Object.keys(selectedAnalyze.result.file_rewrites).length === 0
                    }
                    onClick={() => runDiffReview(selectedIssue, selectedAnalyze.result!, issueSandboxState[selectedIssue.id]?.report)}
                  >
                    {reviewState[selectedIssue.id]?.loading ? (
                      <>
                        <Loader size={15} className="spin" /> Reviewing...
                      </>
                    ) : (
                      <>
                        🔍 Request AI Review
                      </>
                    )}
                  </button>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={
                      prSubmitting[selectedIssue.id] ||
                      Object.keys(selectedAnalyze.result.file_rewrites).length === 0
                    }
                    onClick={() => submitPR(selectedIssue, selectedAnalyze.result!)}
                  >
                    {prSubmitting[selectedIssue.id] ? (
                      <>
                        <Loader size={15} className="spin" /> Creating PR…
                      </>
                    ) : (
                      <>
                        <Plus size={15} /> Create Pull Request
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function CpuIcon() {
  return <Code2 size={19} strokeWidth={1.8} />
}

function SandboxPanel({
  sandboxState,
  healingState,
  activeSubTab,
  setActiveSubTab,
  onRunSandbox,
  onAutoHeal,
}: {
  repoFullName?: string
  title?: string
  fileRewrites?: Record<string, string>
  sandboxState?: { loading: boolean; report?: SandboxReport; error?: string }
  healingState?: { loading: boolean; analysis?: string }
  activeSubTab: 'tests' | 'linter' | 'types' | 'syntax' | 'logs'
  setActiveSubTab: (tab: 'tests' | 'linter' | 'types' | 'syntax' | 'logs') => void
  onRunSandbox: () => void
  onAutoHeal: (report: SandboxReport) => void
}) {
  if (!sandboxState && !healingState) {
    return (
      <div
        style={{
          marginTop: '0.75rem',
          padding: '0.75rem 1rem',
          background: '#f4f8f3',
          border: '1px dashed #b8d4bb',
          borderRadius: '7px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <FlaskConical size={16} style={{ color: '#2b6e3f' }} />
          <div>
            <div style={{ fontSize: '0.8rem', fontWeight: 650, color: '#1a4329' }}>
              Isolated Test Sandbox
            </div>
            <div style={{ fontSize: '0.72rem', color: '#52725e' }}>
              Execute pytest, flake8, and mypy in an isolated workspace before opening PR.
            </div>
          </div>
        </div>
        <button
          type="button"
          className="sandbox-verify-btn"
          onClick={onRunSandbox}
        >
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
      {/* Header */}
      <div className="sandbox-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {loading ? (
            <span className="sandbox-status-badge sandbox-running">
              <Loader size={11} className="spin" />
              {healingState?.loading ? 'Auto-healing code with Ollama…' : 'Running Isolated Pytest & Linters…'}
            </span>
          ) : report?.overall_status === 'passed' ? (
            <span className="sandbox-status-badge sandbox-passed">
              <CheckCircle2 size={12} /> 100% Tests & Linters Passed
            </span>
          ) : report?.overall_status === 'warnings' ? (
            <span className="sandbox-status-badge sandbox-warnings">
              <AlertTriangle size={12} /> Tests Passed with Warnings
            </span>
          ) : report?.overall_status === 'failed' ? (
            <span className="sandbox-status-badge sandbox-failed">
              <XCircle size={12} /> Sandbox Verification Failed
            </span>
          ) : error ? (
            <span className="sandbox-status-badge sandbox-failed">
              <XCircle size={12} /> Sandbox Error
            </span>
          ) : (
            <span className="sandbox-status-badge sandbox-running">
              <FlaskConical size={12} /> Ready to verify
            </span>
          )}

          {report && (
            <span className="sandbox-score-pill">
              Score: {report.score}/100
            </span>
          )}
        </div>

        <div className="sandbox-metrics">
          {report && <span>⚡ {report.execution_time_seconds}s</span>}
          <button
            type="button"
            className="sandbox-verify-btn"
            disabled={loading}
            onClick={onRunSandbox}
            title="Re-run sandbox test suite"
          >
            <RefreshCw size={10} className={loading ? 'spin' : ''} />
            {report ? 'Re-run Sandbox' : 'Run Sandbox'}
          </button>
        </div>
      </div>

      {/* Auto-Heal Banner on Failure */}
      {report?.overall_status === 'failed' && !loading && (
        <div className="sandbox-autoheal-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={16} style={{ color: '#7c3aed', flexShrink: 0 }} />
            <div>
              <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#4c1d95' }}>
                Test failures or syntax issues detected
              </div>
              <div style={{ fontSize: '0.72rem', color: '#6d28d9' }}>
                Let Ollama analyze the pytest tracebacks and automatically heal the code.
              </div>
            </div>
          </div>
          <button
            type="button"
            className="sandbox-heal-btn"
            disabled={healingState?.loading}
            onClick={() => onAutoHeal(report)}
          >
            {healingState?.loading ? (
              <>
                <Loader size={12} className="spin" /> Healing…
              </>
            ) : (
              <>
                <Sparkles size={12} /> ✨ Auto-Heal with Ollama
              </>
            )}
          </button>
        </div>
      )}

      {/* Healing analysis result notice */}
      {healingState?.analysis && !healingState?.loading && (
        <div className="sandbox-healed-box">
          <strong>✨ Ollama Healing Analysis:</strong> {healingState.analysis}
        </div>
      )}

      {/* Sub-tabs */}
      {report && (
        <>
          <div className="sandbox-tabs">
            <button
              type="button"
              className={`sandbox-tab-btn ${activeSubTab === 'tests' ? 'active' : ''}`}
              onClick={() => setActiveSubTab('tests')}
            >
              🧪 Pytest Suite ({report.checks.tests.passed_count}/{report.checks.tests.tests_run || 0})
            </button>
            <button
              type="button"
              className={`sandbox-tab-btn ${activeSubTab === 'linter' ? 'active' : ''}`}
              onClick={() => setActiveSubTab('linter')}
            >
              ⚡ Flake8 ({report.checks.linter.warnings_count} warnings)
            </button>
            <button
              type="button"
              className={`sandbox-tab-btn ${activeSubTab === 'types' ? 'active' : ''}`}
              onClick={() => setActiveSubTab('types')}
            >
              🏷️ Mypy ({report.checks.type_check.errors_count || 0} issues)
            </button>
            <button
              type="button"
              className={`sandbox-tab-btn ${activeSubTab === 'syntax' ? 'active' : ''}`}
              onClick={() => setActiveSubTab('syntax')}
            >
              📝 Syntax ({report.checks.syntax.errors?.length || 0})
            </button>
            <button
              type="button"
              className={`sandbox-tab-btn ${activeSubTab === 'logs' ? 'active' : ''}`}
              onClick={() => setActiveSubTab('logs')}
            >
              🖥️ Terminal Log
            </button>
          </div>

          <div className="sandbox-body">
            {/* Pytest tab */}
            {activeSubTab === 'tests' && (
              <div>
                <div className="sandbox-summary-stats">
                  <div className="sandbox-stat-box">
                    <div className="sandbox-stat-val" style={{ color: '#166534' }}>
                      {report.checks.tests.passed_count}
                    </div>
                    <div className="sandbox-stat-label">Passed</div>
                  </div>
                  <div className="sandbox-stat-box">
                    <div
                      className="sandbox-stat-val"
                      style={{ color: report.checks.tests.failed_count > 0 ? '#b91c1c' : '#374151' }}
                    >
                      {report.checks.tests.failed_count}
                    </div>
                    <div className="sandbox-stat-label">Failed</div>
                  </div>
                  <div className="sandbox-stat-box">
                    <div
                      className="sandbox-stat-val"
                      style={{ color: report.checks.tests.error_count > 0 ? '#b91c1c' : '#374151' }}
                    >
                      {report.checks.tests.error_count}
                    </div>
                    <div className="sandbox-stat-label">Errors</div>
                  </div>
                  <div className="sandbox-stat-box">
                    <div className="sandbox-stat-val">
                      {report.checks.tests.duration_seconds}s
                    </div>
                    <div className="sandbox-stat-label">Duration</div>
                  </div>
                </div>

                {report.checks.tests.failed_count > 0 ? (
                  <div style={{ marginTop: '0.4rem' }}>
                    <div style={{ fontWeight: 650, color: '#991b1b', marginBottom: '0.2rem' }}>
                      Pytest Failure Traceback:
                    </div>
                    <div className="sandbox-terminal">{report.checks.tests.output}</div>
                  </div>
                ) : (
                  <div style={{ color: '#15803d', fontWeight: 500, padding: '4px 0' }}>
                    ✓ {report.checks.tests.summary}
                  </div>
                )}
              </div>
            )}

            {/* Flake8 Linter tab */}
            {activeSubTab === 'linter' && (
              <div>
                {report.checks.linter.warnings && report.checks.linter.warnings.length > 0 ? (
                  <table className="sandbox-lint-table">
                    <thead>
                      <tr>
                        <th>File</th>
                        <th>Line:Col</th>
                        <th>Violation Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.checks.linter.warnings.map((w, idx) => (
                        <tr key={idx}>
                          <td>{w.file}</td>
                          <td>{w.line}:{w.col}</td>
                          <td>{w.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div style={{ color: '#15803d', fontWeight: 500, padding: '4px 0' }}>
                    ✓ Zero lint violations. Code strictly complies with flake8 standards.
                  </div>
                )}
              </div>
            )}

            {/* Mypy Type Checking tab */}
            {activeSubTab === 'types' && (
              <div>
                {report.checks.type_check.errors && report.checks.type_check.errors.length > 0 ? (
                  <div className="sandbox-terminal">
                    {report.checks.type_check.errors.join('\n')}
                  </div>
                ) : (
                  <div style={{ color: '#15803d', fontWeight: 500, padding: '4px 0' }}>
                    ✓ Mypy static type analysis passed without errors.
                  </div>
                )}
              </div>
            )}

            {/* Syntax compilation tab */}
            {activeSubTab === 'syntax' && (
              <div>
                {report.checks.syntax.errors && report.checks.syntax.errors.length > 0 ? (
                  <div className="sandbox-terminal" style={{ color: '#f87171' }}>
                    {report.checks.syntax.errors.map((e, idx) => (
                      <div key={idx}>
                        <strong>{e.file}</strong>: {e.message}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: '#15803d', fontWeight: 500, padding: '4px 0' }}>
                    ✓ Python bytecode compiled cleanly with py_compile across all modified files.
                  </div>
                )}
              </div>
            )}

            {/* Output Logs tab */}
            {activeSubTab === 'logs' && (
              <div className="sandbox-terminal">
                {report.checks.tests.output || 'No output recorded.'}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default App
