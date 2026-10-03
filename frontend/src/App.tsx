import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CheckCircle2,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDot,
  Clock3,
  Code2,
  ExternalLink,
  Flame,
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
} from 'lucide-react'

import './App.css'
import { API_BASE, postJson } from './app/api'
import type {
  ActiveRun,
  AgentRun,
  AgentStep,
  FeatureSuggestion,
  ImplementFeatureResult,
  Issue,
  OllamaHealth,
  PullRequest,
  Repo,
  SandboxReport,
} from './app/types'
import { SandboxPanel } from './app/SandboxPanel'

function App() {
  const [activeTab, setActiveTab] = useState('Overview')
  const [query, setQuery] = useState('')
  const [pythonOnly, setPythonOnly] = useState(
    () => localStorage.getItem('patchwork.python-only') !== 'false',
  )
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => localStorage.getItem('patchwork.notifications-enabled') !== 'false',
  )
  const [toast, setToast] = useState<{ title: string; message: string } | null>(null)
  const [scanning, setScanning] = useState(false)
  const [lastScan, setLastScan] = useState('Today, 09:02')
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [selectedFeature, setSelectedFeature] = useState<FeatureSuggestion | null>(null)
  const [ollamaHealth, setOllamaHealth] = useState<OllamaHealth | null>(null)
  const activeProviderLabel = ollamaHealth?.provider === 'openrouter'
    ? 'OpenRouter'
    : ollamaHealth?.provider === 'ollama'
      ? 'Ollama'
      : ollamaHealth?.provider === 'groq'
        ? 'Groq'
        : 'AI'
  const [telemetry, setTelemetry] = useState<any>(null)
  const [realRepos, setRealRepos] = useState<Repo[]>([])
  const [realIssues, setRealIssues] = useState<Issue[]>([])
  const [features, setFeatures] = useState<FeatureSuggestion[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [agentRunHistory, setAgentRunHistory] = useState<AgentRun[]>([])
  const [pullRequests, setPullRequests] = useState<PullRequest[]>([])
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null)
  const [agentRuns, setAgentRuns] = useState<Record<number, AgentRun>>({})
  const [agentSteps, setAgentSteps] = useState<Record<number, AgentStep[]>>({})
  const previousRunStatuses = useRef<Record<number, string>>({})

  // Per-issue PR submit state
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
  const [issueQuery, setIssueQuery] = useState('')
  const [issueDifficultyFilter, setIssueDifficultyFilter] = useState('all')
  const [issueStatusFilter, setIssueStatusFilter] = useState('all')
  const [issueFiltersOpen, setIssueFiltersOpen] = useState(false)
  const [issuePage, setIssuePage] = useState(1)
  const [issueTotalCount, setIssueTotalCount] = useState(0)

  // Sandbox states
  const [featureSandboxState, setFeatureSandboxState] = useState<
    Record<number, { loading: boolean; report?: SandboxReport; error?: string; activity?: string[] }>
  >({})
  const [featureHealingState, setFeatureHealingState] = useState<
    Record<number, { loading: boolean; analysis?: string }>
  >({})
  const [featureSandboxTab, setFeatureSandboxTab] = useState<
    'tests' | 'linter' | 'types' | 'syntax' | 'logs'
  >('tests')

  function notify(title: string, message: string) {
    if (!notificationsEnabled) return
    setToast({ title, message })
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, { body: message })
    }
  }

  async function toggleNotifications() {
    const next = !notificationsEnabled
    setNotificationsEnabled(next)
    localStorage.setItem('patchwork.notifications-enabled', String(next))

    if (!next) {
      setToast(null)
      return
    }

    if ('Notification' in window && Notification.permission === 'default') {
      await Notification.requestPermission()
    }
    notify('Notifications enabled', 'Patchwork will notify you about discovery and PR updates.')
  }

  function updatePythonOnly(enabled: boolean) {
    setPythonOnly(enabled)
    localStorage.setItem('patchwork.python-only', String(enabled))
    void fetchData(enabled)
  }

  const fetchData = async (filterToPython = pythonOnly) => {

    try {
      fetch(`${API_BASE}/api/telemetry`)
        .then(res => res.json())
        .then(data => setTelemetry(data))
        .catch(() => {})
    } catch {}

    try {
      const [reposRes, issuesRes, runsRes, agentRunsRes, prsRes, featuresRes] = await Promise.all([
        fetch(`${API_BASE}/api/repositories${filterToPython ? '?language=Python' : ''}`),
        fetch(`${API_BASE}/api/issues?limit=20&offset=${(issuePage - 1) * 20}`),
        fetch(`${API_BASE}/api/runs`),
        fetch(`${API_BASE}/api/agent-runs?limit=50`),
        fetch(`${API_BASE}/api/pull-requests`),
        fetch(`${API_BASE}/api/features`),
        
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
        setIssueTotalCount(Number(issuesRes.headers.get('X-Total-Count') ?? 0))
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
        for (const run of runsData) {
          if (
            previousRunStatuses.current[run.id] === 'running' &&
            run.status !== 'running'
          ) {
            notify(
              run.status === 'completed' ? 'Discovery complete' : 'Discovery needs attention',
              run.summary || `Discovery finished with status: ${run.status}`,
            )
          }
          previousRunStatuses.current[run.id] = run.status
        }
        setRuns(runsData)
        const running = runsData.find((r: any) => r.status === 'running') ?? null
        setActiveRun(running)
      }

      if (agentRunsRes.ok) {
        setAgentRunHistory(await agentRunsRes.json())
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
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 5000)
    return () => window.clearTimeout(timeout)
  }, [toast])

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE}/api/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Health request failed')
        return response.json() as Promise<OllamaHealth>
      })
      .then(setOllamaHealth)
      .catch(() => {
        if (!controller.signal.aborted) {
          setOllamaHealth({
            ollama_connected: false,
            configured_model: 'nvidia/nemotron-3-ultra-550b-a55b:free',
            model_available: false,
            provider: 'openrouter',
          })
        }
      })

    fetchData()
    const interval = setInterval(fetchData, 10000)

    return () => {
      controller.abort()
      clearInterval(interval)
    }
  }, [issuePage])

  // Fast-poll while a discovery run is active
  useEffect(() => {
    if (!activeRun) return
    const id = setInterval(fetchData, 2000)
    return () => clearInterval(id)
  }, [activeRun?.id ?? null])

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

  const filteredIssues = useMemo(
    () =>
      realIssues.filter((issue) => {
        const matchesQuery = `${issue.repo} ${issue.title} ${issue.label}`
          .toLowerCase()
          .includes(issueQuery.toLowerCase())
        const matchesDifficulty =
          issueDifficultyFilter === 'all' || issue.difficulty === issueDifficultyFilter
        const matchesStatus =
          issueStatusFilter === 'all' || (issue.agent_status ?? 'unstarted') === issueStatusFilter
        return matchesQuery && matchesDifficulty && matchesStatus
      }),
    [realIssues, issueQuery, issueDifficultyFilter, issueStatusFilter],
  )

  const issuePageSize = 20
  const hasClientIssueFilter = Boolean(
    issueQuery || issueDifficultyFilter !== 'all' || issueStatusFilter !== 'all',
  )
  const issueCountForPagination = hasClientIssueFilter ? filteredIssues.length : issueTotalCount
  const totalIssuePages = Math.max(1, Math.ceil(issueCountForPagination / issuePageSize))
  const currentIssuePage = Math.min(issuePage, totalIssuePages)
  const visibleIssues = activeTab === 'Overview'
    ? filteredIssues.slice(0, 3)
    : filteredIssues

  useEffect(() => {
    setIssuePage(1)
  }, [issueQuery, issueDifficultyFilter, issueStatusFilter])

  const combinedRuns = [
    ...runs.map((run) => ({ ...run, kind: 'discovery' as const })),
    ...agentRunHistory.map((run) => ({ ...run, kind: 'agent' as const })),
  ].sort((left, right) => {
    const leftDate = left.updated_at || left.created_at || ''
    const rightDate = right.updated_at || right.created_at || ''
    return rightDate.localeCompare(leftDate)
  })

  async function runDiscovery() {
    if (scanning) return
    setScanning(true)

    try {
      const response = await fetch(`${API_BASE}/api/discovery/trigger`, {
        method: 'POST',
      })

      if (response.ok) {
        const data = await response.json()
        console.log('Discovery started:', data)
        setLastScan('Running...')
        // Set activeRun immediately so the fast-poll effect kicks in right away
        setActiveRun({ id: data.run_id, name: 'Manual repository discovery', status: 'running', repositories_scanned: 0, issues_found: 0, created_at: 'Just now' })
        fetchData()
      } else {
        const error = await response.json().catch(() => ({}))
        notify('Discovery could not start', error.detail || 'Please try again.')
      }
    } catch (err) {
      console.error('Failed to trigger discovery:', err)
      notify('Discovery could not start', 'Check the backend connection and try again.')
    } finally {
      setTimeout(() => setScanning(false), 2000)
    }
  }

  async function suggestFeatures(repoFullName: string) {
    setSuggestingRepo((prev) => ({ ...prev, [repoFullName]: true }))
    try {
      const res = await fetch(
        `${API_BASE}/api/repositories/${repoFullName}/suggest-features`,
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
    setFeatureSandboxState((prev) => ({
      ...prev,
      [feature.id]: { loading: true, activity: ['Preparing sandbox workspace…'] },
    }))
    setFeatureHealingState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      setFeatureSandboxState((prev) => ({
        ...prev,
        [feature.id]: { ...prev[feature.id], loading: true, activity: ['Preparing sandbox workspace…', 'Running isolated checks…'] },
      }))
      const res = await fetch(`${API_BASE}/api/features/${feature.id}/sandbox-verify`, {
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
      const finalRewrites = report.file_rewrites ?? file_rewrites
      if (report.file_rewrites) {
        setFeatureImplementState((prev) => {
          const existing = prev[feature.id]
          if (!existing?.result) return prev
          return {
            ...prev,
            [feature.id]: {
              ...existing,
              result: { ...existing.result, file_rewrites: finalRewrites },
            },
          }
        })
      }
      setFeatureHealingState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, analysis: report.healing_analysis },
      }))
      setFeatureSandboxState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, report, activity: ['Preparing sandbox workspace…', 'Running isolated checks…', `Sandbox completed: ${report.overall_status}`] },
      }))
      fetchData()
    } catch (err: any) {
      setFeatureSandboxState((prev) => ({
        ...prev,
        [feature.id]: { loading: false, error: err.message ?? 'Sandbox error', activity: ['Preparing sandbox workspace…', 'Running isolated checks…', `Sandbox failed: ${err.message ?? 'unknown error'}`] },
      }))
      setFeatureHealingState((prev) => ({ ...prev, [feature.id]: { loading: false } }))
    }
  }

  async function autoHealFeature(
    feature: FeatureSuggestion,
    currentRewrites: Record<string, string>,
    diagnostics: SandboxReport,
  ) {
    setFeatureHealingState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      const res = await fetch(`${API_BASE}/api/sandbox/auto-heal`, {
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

  async function implementFeature(feature: FeatureSuggestion) {
    setFeatureImplementState((prev) => ({ ...prev, [feature.id]: { loading: true } }))
    try {
      const res = await fetch(`${API_BASE}/api/features/${feature.id}/implement`, {
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
      const res = await fetch(`${API_BASE}/api/features/${feature.id}/create-pr`, {
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
      notify('Pull request created', `${pr.repository}: ${pr.title}`)
      fetchData()
      setSelectedFeature(null)
    } catch (err: any) {
      alert(`Feature PR creation failed: ${err.message}`)
    } finally {
      setFeaturePrSubmitting((prev) => ({ ...prev, [feature.id]: false }))
    }
  }

  async function startAgentWorkflow(issue: Issue) {
    setAgentRuns((prev) => ({
      ...prev,
      [issue.id]: {
        id: 0,
        issue_id: issue.id,
        status: 'starting',
        current_step: 'queued',
        attempt: 0,
        model_requests: 0,
        estimated_tokens: 0,
      },
    }))
    try {
      const data = await postJson<AgentRun>('/api/agent-runs', {
        issue_id: issue.id,
        idempotency_key: `dashboard:issue:${issue.id}`,
      })
      setAgentRuns((prev) => ({ ...prev, [issue.id]: data }))

      const poll = async () => {
        const [runResponse, stepsResponse] = await Promise.all([
          fetch(`${API_BASE}/api/agent-runs/${data.id}`),
          fetch(`${API_BASE}/api/agent-runs/${data.id}/steps`),
        ])
        if (!runResponse.ok) return
        const run: AgentRun = await runResponse.json()
        setAgentRuns((prev) => ({ ...prev, [issue.id]: run }))
        if (stepsResponse.ok) {
          const steps: AgentStep[] = await stepsResponse.json()
          setAgentSteps((prev) => ({ ...prev, [issue.id]: steps }))
        }
        if (!['awaiting_approval', 'completed', 'failed', 'cancelled'].includes(run.status)) {
          window.setTimeout(() => void poll(), 2000)
        }
      }
      void poll()
      notify('Agent workflow started', `${activeProviderLabel} is planning and validating this issue.`)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to start agent workflow'
      setAgentRuns((prev) => ({
        ...prev,
        [issue.id]: { ...prev[issue.id], status: 'failed', failure_reason: message } as AgentRun,
      }))
      notify('Agent workflow failed', message)
    }
  }

  async function approveAgentPR(issue: Issue, run: AgentRun) {
    try {
      const data = await postJson<PullRequest>(`/api/agent-runs/${run.id}/approve-pr`, {
        reviewer: 'dashboard-user',
      })
      setPullRequests((prev) => [data, ...prev])
      setAgentRuns((prev) => ({ ...prev, [issue.id]: { ...run, status: 'monitoring_ci' } }))
      notify('Pull request created', data.url || `PR for ${issue.repo}`)
    } catch (err) {
      notify('Approval failed', err instanceof Error ? err.message : 'Unable to create pull request')
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
  const selectedAgentRun = selectedIssue ? agentRuns[selectedIssue.id] : undefined
  const selectedAgentSteps = selectedIssue ? agentSteps[selectedIssue.id] ?? [] : []
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
            count={issueTotalCount || realIssues.length || undefined}
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
                ? `${activeProviderLabel} connected`
                : `${ollamaHealth.provider ?? 'llm'} unavailable`
              : 'Checking LLM...'}
          </div>
          <div className="model-name">{ollamaHealth?.configured_model ?? 'qwen3.5:9b'}</div>
          <div className="setup-meta">
            <span>{activeProviderLabel}</span>
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
                  ? `${activeProviderLabel} online`
                  : `${ollamaHealth.provider === 'openrouter' ? 'OpenRouter' : 'LLM'} offline`
                : 'Checking model provider'}
            </span>
            <button
              className={`icon-button notification-button ${notificationsEnabled ? 'notification-enabled' : ''}`}
              type="button"
              title={notificationsEnabled ? 'Turn notifications off' : 'Turn notifications on'}
              aria-label={notificationsEnabled ? 'Turn notifications off' : 'Turn notifications on'}
              aria-pressed={notificationsEnabled}
              onClick={() => void toggleNotifications()}
            >
              <Bell size={17} />
              {notificationsEnabled && <i />}
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
              {isOverview && (
              <button
                className="button button-primary"
                type="button"
                onClick={runDiscovery}
                disabled={scanning || !!activeRun}
              >
                {(scanning || activeRun) ? (
                  <>
                    <Loader size={16} className="spin" /> Scanning...
                  </>
                ) : (
                  <>
                    <Play size={16} /> Run discovery
                  </>
                )}
              </button>
              )}
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
                <div className="metric-value">{issueTotalCount || realIssues.length}</div>
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
                  <span>AI MODEL</span>
                  <Terminal size={16} />
                </div>
                <div className="model-metric">
                  <span className="model-orbit">
                    <CpuIcon />
                  </span>
                  <span>
                    <strong>{ollamaHealth?.configured_model ?? 'qwen3.5:9b'}</strong>
                    <small>Served via {ollamaHealth?.provider ?? 'configured provider'}</small>
                  </span>
                </div>
                <div className="metric-foot">
                  <span className="model-live">
                    <span
                      className={`online-dot ${ollamaHealth?.model_available ? '' : 'offline'}`}
                    />{' '}
                    {ollamaHealth?.model_available ? 'Model ready' : 'Not available'}
                  </span>
                  <span>{ollamaHealth?.provider === 'ollama' ? 'Runs locally' : 'Hosted inference'}</span>
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
                    onClick={() => updatePythonOnly(!pythonOnly)}
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
                        {(issueTotalCount || realIssues.length).toString().padStart(2, '0')}
                      </span>
                    </h2>
                  </div>
                  <button
                    className={`icon-button panel-more ${issueFiltersOpen ? 'filter-active' : ''}`}
                    type="button"
                    title="Issue filters"
                    aria-label="Issue filters"
                    aria-expanded={issueFiltersOpen}
                    onClick={() => setIssueFiltersOpen((open) => !open)}
                  >
                    <Settings2 size={16} />
                  </button>
                </div>
                {issueFiltersOpen && (
                  <div className="issue-filter-bar">
                    <label className="search-field">
                      <Search size={14} />
                      <input
                        value={issueQuery}
                        onChange={(event) => setIssueQuery(event.target.value)}
                        placeholder="Search issues"
                        aria-label="Search issues"
                      />
                      {issueQuery && (
                        <button type="button" aria-label="Clear issue search" onClick={() => setIssueQuery('')}>
                          <X size={13} />
                        </button>
                      )}
                    </label>
                    <select
                      className="repo-select"
                      value={issueDifficultyFilter}
                      onChange={(event) => setIssueDifficultyFilter(event.target.value)}
                      aria-label="Filter by difficulty"
                    >
                      <option value="all">All difficulty</option>
                      <option value="Good first issue">Good first issue</option>
                      <option value="Intermediate">Intermediate</option>
                    </select>
                    <select
                      className="repo-select"
                      value={issueStatusFilter}
                      onChange={(event) => setIssueStatusFilter(event.target.value)}
                      aria-label="Filter by agent status"
                    >
                      <option value="all">All statuses</option>
                      <option value="unstarted">Unstarted</option>
                      <option value="analyzing">Analyzing</option>
                      <option value="analyzed">Patch ready</option>
                      <option value="pr_created">PR created</option>
                    </select>
                  </div>
                )}
                <div className="issue-list">
                  {filteredIssues.length > 0 ? (
                    visibleIssues.map((issue) => (
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
                        {realIssues.length > 0 ? 'No issues match these filters' : 'No issues discovered yet'}
                      </p>
                      <p style={{ fontSize: '0.85rem', opacity: 0.7 }}>
                        {realIssues.length > 0
                          ? 'Try a different search or status.'
                          : 'Run discovery to find contribution opportunities'}
                      </p>
                    </div>
                  )}
                </div>
                {!isOverview && issueCountForPagination > issuePageSize && (
                  <div className="issue-pagination" aria-label="Issue queue pagination">
                    <button
                      className="icon-button"
                      type="button"
                      onClick={() => setIssuePage((page) => Math.max(1, page - 1))}
                      disabled={currentIssuePage === 1}
                      aria-label="Previous issue page"
                      title="Previous issue page"
                    >
                      <ChevronLeft size={14} />
                    </button>
                    <span>
                      Page {currentIssuePage} of {totalIssuePages}
                    </span>
                    <button
                      className="icon-button"
                      type="button"
                      onClick={() => setIssuePage((page) => Math.min(totalIssuePages, page + 1))}
                      disabled={currentIssuePage === totalIssuePages}
                      aria-label="Next issue page"
                      title="Next issue page"
                    >
                      <ChevronRight size={14} />
                    </button>
                  </div>
                )}
                {realIssues.length > 0 && (
                  <button
                    className="queue-link"
                    type="button"
                    onClick={() => setActiveTab(isOverview ? 'Issue queue' : 'Overview')}
                  >
                    {isOverview ? 'Open full issue queue' : 'Back to overview'} <ArrowRight size={14} />
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
                {combinedRuns.length > 0 ? (
                  combinedRuns.map((run) => (
                    <div key={`${run.kind}-${run.id}`}>
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
                        <strong>
                          {run.kind === 'agent'
                            ? `Issue agent${run.issue_number ? ` #${run.issue_number}` : ''}`
                            : run.name}
                        </strong>
                        <small>
                          {run.kind === 'agent'
                            ? `${run.repository ?? 'Unknown repository'}${run.issue_title ? ` · ${run.issue_title}` : ''}`
                            : run.summary || 'In progress...'}
                        </small>
                        {run.kind === 'agent' && run.status === 'failed' && run.failure_reason && (
                          <small className="run-failure">Failure: {run.failure_reason}</small>
                        )}
                      </span>
                      <b>
                        {run.kind === 'agent'
                          ? run.status === 'completed'
                            ? 'Completed'
                            : run.status === 'failed'
                              ? 'Failed'
                              : 'Running'
                          : run.status === 'completed'
                          ? 'Completed'
                          : run.status === 'failed'
                          ? 'Failed'
                          : 'Running'}{' '}
                        <small>{run.created_at || run.updated_at}</small>
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
                  onClick={() => updatePythonOnly(!pythonOnly)}
                >
                  <span />
                </button>
              </div>
              <div className="settings-row">
                <span>
                  <strong>Notifications</strong>
                  <small>Discovery results and pull request updates</small>
                </span>
                <button
                  className={`toggle ${notificationsEnabled ? 'toggle-on' : ''}`}
                  type="button"
                  aria-label="Toggle notifications"
                  aria-pressed={notificationsEnabled}
                  onClick={() => void toggleNotifications()}
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
                  <small>Served via {ollamaHealth?.provider ?? 'configured provider'}</small>
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
                    {activeProviderLabel} will read the target files in {selectedFeature.repository} and synthesize
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

                <SandboxPanel
                  repoFullName={selectedFeature.repository}
                  title={selectedFeature.title}
                  providerLabel={activeProviderLabel}
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
                      <Sparkles size={15} /> Implement with {activeProviderLabel}
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
                      featureSandboxState[selectedFeature.id]?.loading === true ||
                      featureHealingState[selectedFeature.id]?.loading === true ||
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
                    ) : featureSandboxState[selectedFeature.id]?.loading || featureHealingState[selectedFeature.id]?.loading ? (
                      <>
                        <Loader size={15} className="spin" /> Sandbox running…
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

            <div className="agent-run-summary" aria-live="polite">
              {selectedAgentRun ? (
                <>
                  <strong>Agent workflow: {selectedAgentRun.status}</strong>
                  <span>Step: {selectedAgentRun.current_step} · Model requests: {selectedAgentRun.model_requests}</span>
                  {selectedAgentRun.failure_reason && <span className="agent-run-error">{selectedAgentRun.failure_reason}</span>}
                </>
              ) : (
                <>
                  <strong>Ready for full agent workflow</strong>
                  <span>{activeProviderLabel} will plan, test, implement, review, and wait for approval before creating a PR.</span>
                </>
              )}
            </div>

            {selectedAgentRun && (
              <div className="sandbox-live-console agent-live-console" aria-live="polite">
                <div className="sandbox-live-console-title">Agent console</div>
                {selectedAgentSteps.map((step) => (
                  <div key={step.id}>
                    $ {step.step_key} [{step.status}]
                    {step.error ? `: ${step.error}` : ''}
                  </div>
                ))}
                {selectedAgentRun.status !== 'completed' && selectedAgentRun.status !== 'failed' && (
                  <div className="sandbox-console-cursor">$ {selectedAgentRun.current_step} running…</div>
                )}
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

              <button
                className="button button-primary"
                type="button"
                disabled={selectedAgentRun?.status === 'starting' || selectedAgentRun?.status === 'planning' || selectedAgentRun?.status === 'executing'}
                onClick={() => void startAgentWorkflow(selectedIssue)}
              >
                {selectedAgentRun?.status === 'starting' || selectedAgentRun?.status === 'planning' || selectedAgentRun?.status === 'executing' ? (
                  <><Loader size={15} className="spin" /> Running full {activeProviderLabel} workflow…</>
                ) : (
                  <><Wand2 size={15} /> Run full agent with {activeProviderLabel}</>
                )}
              </button>
              {selectedAgentRun?.status === 'awaiting_approval' && (
                <button className="button button-primary" type="button" onClick={() => void approveAgentPR(selectedIssue, selectedAgentRun)}>
                  <CheckCircle2 size={15} /> Approve PR
                </button>
              )}
            </div>
          </section>
        </div>
      )}
      {toast && (
        <div className="notification-toast" role="status" aria-live="polite">
          <div>
            <strong>{toast.title}</strong>
            <span>{toast.message}</span>
          </div>
          <button type="button" aria-label="Dismiss notification" onClick={() => setToast(null)}>
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  )
}

function CpuIcon() {
  return <Code2 size={19} strokeWidth={1.8} />
}

export default App
