"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import Link from "next/link";
import GridLayout, { useContainerWidth } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  Database,
  LayoutDashboard,
  LockKeyhole,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RefreshCw,
  Route,
  Sparkles,
  UnlockKeyhole,
  X,
} from "lucide-react";
import {
  CatalogSchema,
  DashboardSchema,
  HealthSchema,
  ResponseSchema,
  SessionSchema,
  SessionSummarySchema,
  ChatRequestSchema,
  type Catalog,
  type Dashboard,
  type Dataset,
  type Filters,
  type Health,
  type Response,
  type Session,
  type SessionSummary,
  type Stage,
} from "@/lib/contracts.generated";
import { api } from "@/lib/api";
import { applyAnalysis, emptyDashboard, emptyFilters, validateDashboard } from "@/lib/dashboard";
import { consumeStream } from "@/lib/stream";
import { formatDate, number } from "@/lib/utils";
import { WidgetCard } from "./widget";
import { FilterPanel } from "./filter-panel";
import { InvestigationChat } from "./ai-elements/chat";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogTrigger } from "./ui/dialog";

type View = { session: Session; dashboard: Dashboard; datasets: Dataset[] };
function fromSession(session: Session): View {
  validateDashboard(session.dashboard, session.datasets);
  return { session, dashboard: session.dashboard, datasets: session.datasets };
}
export function Workspace() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [view, setView] = useState<View | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stages, setStages] = useState<Stage[]>([]);
  const [showChat, setShowChat] = useState(true);
  const [mobileTab, setMobileTab] = useState<"dashboard" | "chat">("dashboard");
  const [locked, setLocked] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const { width, containerRef, mounted } = useContainerWidth();
  const current = useRef<View | null>(null);
  const abort = useRef<AbortController | null>(null);
  const saveQueue = useRef(Promise.resolve());
  const loadGeneration = useRef(0);
  function updateView(next: View) {
    current.current = next;
    setView(next);
  }
  const acceptAnalysis = useCallback((response: Response, appendMessage = false) => {
    const existing = current.current;
    if (!existing || response.session_id !== existing.session.id) return;
    const applied = applyAnalysis(existing.dashboard, existing.datasets, response);
    const messages = [...existing.session.messages];
    if (
      appendMessage &&
      response.answer &&
      !messages.some((message) => message.analysis_id === response.analysis_id)
    )
      messages.push({
        id: response.analysis_id,
        role: "assistant",
        content: response.answer,
        analysis_id: response.analysis_id,
      });
    const activeFilters =
      response.status === "complete" && response.datasets[0]
        ? response.datasets[0].query.filters
        : existing.session.active_filters;
    const next = {
      session: {
        ...existing.session,
        messages,
        latest_analysis: response,
        active_filters: activeFilters,
      },
      dashboard: applied.dashboard,
      datasets: applied.datasets,
    };
    current.current = next;
    setView(next);
    setSuggestions(response.suggestions);
    if (response.status === "complete" && response.datasets[0])
      setFilters(response.datasets[0].query.filters);
  }, []);
  const initialize = useCallback(async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError("");
    try {
      const [nextCatalog, nextHealth, list] = await Promise.all([
        api("/catalog", CatalogSchema),
        api("/health", HealthSchema),
        api("/sessions", z.array(SessionSummarySchema)),
      ]);
      if (generation !== loadGeneration.current) return;
      setCatalog(nextCatalog);
      setHealth(nextHealth);
      setSessions(list);
      const savedId = localStorage.getItem("via-session");
      const id = list.find((session) => session.id === savedId)?.id ?? list[0]?.id;
      const session = id
        ? await api(`/sessions/${id}`, SessionSchema)
        : await api("/sessions", SessionSchema, { method: "POST" });
      if (generation !== loadGeneration.current) return;
      current.current = fromSession(session);
      setView(current.current);
      localStorage.setItem("via-session", session.id);
      setFilters(session.active_filters ?? emptyFilters());
      setSuggestions(session.latest_analysis?.suggestions ?? []);
      if (!session.dashboard.widgets.length && nextCatalog.available)
        acceptAnalysis(await api(`/sessions/${session.id}/overview`, ResponseSchema));
      if (!list.some((item) => item.id === session.id))
        setSessions([{ id: session.id, title: session.title }, ...list]);
    } catch (cause) {
      if (generation === loadGeneration.current)
        setError(cause instanceof Error ? cause.message : "Não foi possível carregar o painel.");
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [acceptAnalysis]);
  const invalidateLoad = useCallback(() => {
    ++loadGeneration.current;
    abort.current?.abort();
  }, []);
  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (mounted) void initialize();
    });
    return () => {
      mounted = false;
      invalidateLoad();
    };
  }, [initialize, invalidateLoad]);
  async function selectSession(id: string) {
    if (busy || loading) return;
    setLoading(true);
    setError("");
    try {
      const session = await api(`/sessions/${id}`, SessionSchema);
      updateView(fromSession(session));
      localStorage.setItem("via-session", id);
      setFilters(session.active_filters ?? emptyFilters());
      setSuggestions(session.latest_analysis?.suggestions ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao abrir investigação.");
    } finally {
      setLoading(false);
    }
  }
  async function newSession() {
    if (busy || loading) return;
    setLoading(true);
    setError("");
    try {
      const session = await api("/sessions", SessionSchema, { method: "POST" });
      updateView(fromSession(session));
      localStorage.setItem("via-session", session.id);
      setSessions((list) => [{ id: session.id, title: session.title }, ...list]);
      setFilters(emptyFilters());
      setSuggestions([]);
      if (catalog?.available)
        acceptAnalysis(await api(`/sessions/${session.id}/overview`, ResponseSchema));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao criar investigação.");
    } finally {
      setLoading(false);
    }
  }
  function persist(dashboard: Dashboard) {
    const existing = current.current;
    if (!existing || busy) return;
    try {
      DashboardSchema.parse(dashboard);
      validateDashboard(dashboard, existing.datasets);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Layout inválido.");
      return;
    }
    updateView({ ...existing, dashboard });
    // Serialize layout changes so a slower old request cannot overwrite a new edit.
    const queued = saveQueue.current
      .catch(() => {})
      .then(async () => {
        await api(`/sessions/${existing.session.id}/dashboard`, DashboardSchema, {
          method: "PATCH",
          body: JSON.stringify(dashboard),
        });
      })
      .catch((cause: unknown) => {
        setError(
          cause instanceof Error
            ? cause.message
            : "Não foi possível salvar o layout. Atualize para recuperar a versão salva.",
        );
        throw cause;
      });
    saveQueue.current = queued;
    // A chat run awaits this same promise; failed pinning cannot be silently ignored.
    void queued.catch(() => {});
  }
  const applyFilters = useCallback(
    async (nextFilters: Filters) => {
      const existing = current.current;
      if (!existing || busy) return;
      setBusy(true);
      setError("");
      try {
        await saveQueue.current;
        const response = await api(`/sessions/${existing.session.id}/overview`, ResponseSchema, {
          method: "POST",
          body: JSON.stringify(nextFilters),
        });
        acceptAnalysis(response);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Não foi possível aplicar os filtros.");
      } finally {
        setBusy(false);
      }
    },
    [acceptAnalysis, busy],
  );
  const onChartFilter = useCallback(
    (dimension: string, key: string) => {
      const mapping: Record<string, string> = {
        road: "roads",
        uf: "ufs",
        concession: "concessions",
        accident_type: "accident_types",
        direction: "directions",
        track_type: "track_types",
        vehicle_type: "vehicle_types",
      };
      const field = mapping[dimension];
      if (field) void applyFilters({ ...filters, [field]: [key] });
      else if (dimension === "road_uf") {
        const match = /(?:BR-?)?(\d{3})[^A-Z]*([A-Z]{2})/.exec(key);
        if (match) void applyFilters({ ...filters, roads: [`BR-${match[1]}`], ufs: [match[2]] });
      }
    },
    [filters, applyFilters],
  );
  async function send(message: string) {
    const existing = current.current;
    if (!existing || busy || !health?.llm_configured || !catalog?.available) return;
    setBusy(true);
    setError("");
    setStages([]);
    setMobileTab("chat");
    const requestId = crypto.randomUUID();
    updateView({
      ...existing,
      session: {
        ...existing.session,
        messages: [
          ...existing.session.messages,
          { id: requestId, role: "user", content: message, analysis_id: null },
        ],
      },
    });
    const controller = new AbortController();
    abort.current = controller;
    try {
      await saveQueue.current;
      const request = ChatRequestSchema.parse({
        message,
        session_id: existing.session.id,
        request_id: requestId,
        filters,
      });
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
      let streamRun: string | null = null;
      await consumeStream(response, (event) => {
        if (current.current?.session.id !== existing.session.id) return;
        if (streamRun && event.data.run_id !== streamRun)
          throw new Error("O servidor misturou duas execuções. O painel foi preservado.");
        streamRun = event.data.run_id;
        if (event.event === "completed") {
          if (event.data.request_id !== requestId || event.data.session_id !== existing.session.id)
            throw new Error("A resposta não corresponde a esta pergunta.");
          acceptAnalysis(event.data, true);
        } else
          setStages((items) =>
            items.some((item) => item.stage === event.data.stage) ? items : [...items, event.data],
          );
      });
      setSessions(await api("/sessions", z.array(SessionSummarySchema)));
    } catch (cause) {
      setError(
        controller.signal.aborted
          ? "Análise interrompida. Os resultados anteriores foram preservados."
          : cause instanceof Error
            ? cause.message
            : "A análise não pôde ser concluída.",
      );
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }
  const dashboard = view?.dashboard ?? emptyDashboard();
  const synthetic = catalog?.warnings.some((warning) => /sint[eé]tic/i.test(warning)) ?? false;
  const pinnedCount = dashboard.pinned_widget_ids.length;
  const widgets = dashboard.widgets;
  const partialCoverage =
    view?.datasets.some(
      (dataset) =>
        dataset.evidence.coverage === "partial" &&
        widgets.some((widget) => widget.dataset_id === dataset.id),
    ) ?? false;
  const layouts = dashboard.layouts.lg ?? [];
  const metricWidgets = widgets.filter((widget) => widget.type === "metric");
  const chartWidgets = widgets.filter((widget) => widget.type !== "metric");
  const gridLayout = widgets.map((widget) => {
    const stored = layouts.find((item) => item.i === widget.id);
    const metric = widget.type === "metric";
    const index = (metric ? metricWidgets : chartWidgets).findIndex(
      (item) => item.id === widget.id,
    );
    const defaults = metric
      ? { i: widget.id, x: (index % 4) * 3, y: Math.floor(index / 4) * 4, w: 3, h: 4 }
      : {
          i: widget.id,
          x: (index % 2) * 6,
          y: Math.ceil(metricWidgets.length / 4) * 4 + Math.floor(index / 2) * 7,
          w: 6,
          h: 7,
        };
    return {
      ...(stored ?? defaults),
      minW: metric ? 3 : 4,
      minH: metric ? 4 : 7,
      maxH: 30,
      maxW: 12,
      static: locked || busy,
    };
  });
  const chips = Object.entries(filters).flatMap(([key, value]) =>
    Array.isArray(value)
      ? value.map((item: string) => ({ key, value: item }))
      : key === "severity" && value !== "all"
        ? [
            {
              key,
              value:
                (
                  {
                    with_severe: "Com vítimas graves",
                    with_deaths: "Com óbitos",
                    with_injuries: "Com feridos",
                  } as Record<string, string>
                )[String(value)] ?? String(value),
            },
          ]
        : [],
  );
  const unavailable = loading
    ? "Carregando sua investigação…"
    : !catalog?.available
      ? "Importe os dados da ANTT para iniciar uma investigação."
      : !health?.llm_configured
        ? "Assistente indisponível: configure a chave do modelo no backend. O painel e os filtros continuam disponíveis."
        : "";
  function renderWidget(widget: Dashboard["widgets"][number]) {
    const dataset = view?.datasets.find((item) => item.id === widget.dataset_id);
    if (!dataset) return <div className="notice">Resultado indisponível.</div>;
    return (
      <motion.div
        className="widget-motion"
        initial={{ opacity: 0, y: 5 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <WidgetCard
          widget={widget}
          dataset={dataset}
          pinned={dashboard.pinned_widget_ids.includes(widget.id)}
          locked={locked || busy}
          onPin={() =>
            persist({
              ...dashboard,
              pinned_widget_ids: dashboard.pinned_widget_ids.includes(widget.id)
                ? dashboard.pinned_widget_ids.filter((id) => id !== widget.id)
                : [...dashboard.pinned_widget_ids, widget.id],
            })
          }
          onRemove={() =>
            persist({
              ...dashboard,
              widgets: widgets.filter((item) => item.id !== widget.id),
              pinned_widget_ids: dashboard.pinned_widget_ids.filter((id) => id !== widget.id),
              layouts: Object.fromEntries(
                Object.entries(dashboard.layouts).map(([breakpoint, items]) => [
                  breakpoint,
                  items.filter((item) => item.i !== widget.id),
                ]),
              ),
            })
          }
          onFilter={onChartFilter}
        />
      </motion.div>
    );
  }
  return (
    <MotionConfig reducedMotion="user">
      <div className={`app-shell ${showChat ? "has-chat" : ""}`}>
        <nav className="rail" aria-label="Navegação principal">
          <Link className="brand-symbol" href="/" aria-label="Via início">
            <Route size={25} />
          </Link>
          <div className="rail-items">
            <button
              className="rail-button active"
              aria-label="Dashboard"
              onClick={() => setMobileTab("dashboard")}
            >
              <LayoutDashboard size={20} />
            </button>
            <button
              className="rail-button"
              aria-label="Abrir investigação"
              onClick={() => {
                setShowChat(true);
                setMobileTab("chat");
              }}
            >
              <MessageSquare size={20} />
            </button>
            <Dialog>
              <DialogTrigger asChild>
                <button className="rail-button" aria-label="Sobre os dados">
                  <Database size={20} />
                </button>
              </DialogTrigger>
              <DialogContent title="Sobre os dados">
                <div className="sources">
                  <p>
                    Dados abertos de acidentes em rodovias federais concedidas acompanhadas pela
                    ANTT.
                  </p>
                  <dl>
                    <div>
                      <dt>Cobertura observada</dt>
                      <dd>
                        {formatDate(catalog?.min_date)} a {formatDate(catalog?.max_date)}
                      </dd>
                    </div>
                    <div>
                      <dt>Acidentes</dt>
                      <dd>{catalog?.available ? number.format(catalog.total_accidents) : "—"}</dd>
                    </div>
                    <div>
                      <dt>Recursos</dt>
                      <dd>{catalog?.resources ?? 0}</dd>
                    </div>
                  </dl>
                  {catalog?.warnings.map((warning) => (
                    <p className="notice" key={warning}>
                      {warning}
                    </p>
                  ))}
                  <p className="muted">
                    Contagens não medem risco sem volume de tráfego. Um período sem registros não
                    comprova ausência de acidentes.
                  </p>
                </div>
              </DialogContent>
            </Dialog>
          </div>
          <div className="rail-bottom">
            <ThemeToggle />
            <Dialog>
              <DialogTrigger asChild>
                <button className="rail-button" aria-label="Ajuda">
                  <CircleHelp size={19} />
                </button>
              </DialogTrigger>
              <DialogContent title="Como investigar">
                <div className="sources">
                  <p>
                    Pergunte sobre períodos, rodovias, estados e gravidade. Continue com “desses
                    trechos” para aprofundar o mesmo grupo.
                  </p>
                  <p>
                    Fixe um resultado para preservá-lo ao fazer novas perguntas. Bloquear layout
                    impede apenas movimentação e redimensionamento.
                  </p>
                  <p>
                    Em cada widget, abra o ícone de informação para conferir fonte, recorte e versão
                    da base.
                  </p>
                </div>
              </DialogContent>
            </Dialog>
            <span className="rail-avatar">V</span>
          </div>
        </nav>
        <header className="topbar">
          <div className="brand-wordmark">
            via<span>Inteligência Rodoviária</span>
          </div>
          <div className="topbar-actions">
            <div className="mobile-theme">
              <ThemeToggle />
            </div>
            <span className="source-pill">
              <i />
              {catalog?.available
                ? synthetic
                  ? "Demonstração · dados sintéticos"
                  : "Dados ANTT"
                : "Base não importada"}
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowChat(!showChat)}
              aria-label={showChat ? "Recolher investigação" : "Mostrar investigação"}
            >
              {showChat ? <PanelRightClose size={19} /> : <PanelRightOpen size={19} />}
            </Button>
          </div>
        </header>
        <div className="workspace-body">
          <main className={`dashboard-main mobile-${mobileTab}`}>
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  <span className="tiny-line" />
                  OBSERVATÓRIO DE SEGURANÇA
                </div>
                <h1>
                  Um olhar mais claro
                  <br className="mobile-break" /> sobre as rodovias.
                </h1>
                <p>Explore os dados. Conecte os pontos. Encontre respostas.</p>
              </div>
              <Button
                variant="outline"
                onClick={() => void initialize()}
                disabled={loading || busy}
                aria-label="Atualizar dados do painel"
              >
                <RefreshCw size={15} className={loading ? "spin" : ""} />
                <span className="desktop-label">Atualizar</span>
              </Button>
            </div>
            <div className="dashboard-toolbar">
              <div className="toolbar-left">
                <label className="session-select">
                  <LayoutDashboard size={15} />
                  <select
                    aria-label="Selecionar investigação"
                    value={view?.session.id ?? ""}
                    onChange={(event) => void selectSession(event.target.value)}
                    disabled={busy || loading}
                  >
                    {sessions.map((session) => (
                      <option value={session.id} key={session.id}>
                        {session.title}
                      </option>
                    ))}
                    {view && !sessions.some((session) => session.id === view.session.id) && (
                      <option value={view.session.id}>{view.session.title}</option>
                    )}
                  </select>
                  <ChevronDown size={13} />
                </label>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => void newSession()}
                  disabled={busy || loading}
                  aria-label="Nova investigação"
                >
                  <Plus size={16} />
                </Button>
              </div>
              <div className="toolbar-right">
                <span className="date-display">
                  <CalendarDays size={14} />
                  {formatDate(filters.start_date ?? catalog?.min_date)} —{" "}
                  {formatDate(filters.end_date ?? catalog?.max_date)}
                  {filters.end_date ? " (fim exclusivo)" : ""}
                </span>
                <FilterPanel
                  filters={filters}
                  catalog={catalog}
                  disabled={busy || loading || !catalog?.available}
                  onApply={(next) => void applyFilters(next)}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setLocked(!locked)}
                  aria-label={locked ? "Desbloquear layout" : "Bloquear layout"}
                  aria-pressed={locked}
                >
                  {locked ? <LockKeyhole size={15} /> : <UnlockKeyhole size={15} />}
                </Button>
              </div>
            </div>
            {!!chips.length && (
              <div className="filter-chips">
                {chips.map((chip) => (
                  <button
                    key={`${chip.key}-${chip.value}`}
                    disabled={busy}
                    onClick={() =>
                      void applyFilters({
                        ...filters,
                        [chip.key]: chip.key === "severity" ? "all" : [],
                      })
                    }
                  >
                    {chip.value}
                    <X size={11} />
                  </button>
                ))}
                <button disabled={busy} onClick={() => void applyFilters(emptyFilters())}>
                  Limpar recorte
                </button>
              </div>
            )}
            <AnimatePresence>
              {error && (
                <motion.div
                  className="error-banner"
                  role="alert"
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  <span>{error}</span>
                  <button aria-label="Dispensar aviso" onClick={() => setError("")}>
                    <X size={16} />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
            {partialCoverage && (
              <div className="coverage-banner coverage-partial" role="status">
                <AlertTriangle size={14} />
                Cobertura parcial no período: resultados descrevem os registros disponíveis.
                Consulte as fontes.
              </div>
            )}
            {catalog?.warnings.slice(0, partialCoverage ? 1 : 2).map((warning) => (
              <div className="coverage-banner" key={warning}>
                <InfoIcon />
                {warning}
              </div>
            ))}
            <div className="section-label">
              <span>
                VISÃO GERAL <i>{widgets.length} visualizações</i>
              </span>
              <span>
                {pinnedCount > 0 &&
                  `${pinnedCount} ${pinnedCount === 1 ? "resultado fixado" : "resultados fixados"}`}
                <span className="live-dot" />
                {busy
                  ? "Atualizando análise"
                  : catalog?.available
                    ? "Exploração ao vivo"
                    : "Aguardando dados"}
              </span>
            </div>
            <div ref={containerRef} className="dashboard-grid">
              {loading && !widgets.length ? (
                <div className="loading-grid">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <div className={`skeleton skeleton-${i}`} key={i} />
                  ))}
                </div>
              ) : !widgets.length ? (
                <div className="empty-dashboard">
                  <div className="empty-symbol">
                    <Activity size={34} />
                  </div>
                  <span className="eyebrow">SEU PRÓXIMO INSIGHT COMEÇA AQUI</span>
                  <h2>
                    {catalog?.available
                      ? "Um espaço para descobrir."
                      : "Vamos trazer os dados para a estrada."}
                  </h2>
                  <p>
                    {catalog?.available
                      ? "Faça uma pergunta no assistente ou ajuste os filtros para criar sua primeira análise."
                      : "Importe os arquivos da ANTT para visualizar indicadores, tendências e padrões. Nenhum número demonstrativo é exibido neste painel."}
                  </p>
                  {!catalog?.available && <code>road-safety ingest</code>}
                  {catalog?.available && (
                    <Button onClick={() => void applyFilters(filters)}>
                      Carregar visão geral
                      <ArrowRight size={15} />
                    </Button>
                  )}
                </div>
              ) : mounted && width >= 720 ? (
                <GridLayout
                  width={width}
                  layout={gridLayout}
                  gridConfig={{
                    cols: 12,
                    rowHeight: 35,
                    margin: [18, 18],
                    containerPadding: [0, 0],
                  }}
                  dragConfig={{ enabled: !locked && !busy, handle: ".drag-handle" }}
                  resizeConfig={{ enabled: !locked && !busy }}
                  onDragStop={(layout) =>
                    persist({
                      ...dashboard,
                      layouts: {
                        ...dashboard.layouts,
                        lg: layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
                      },
                    })
                  }
                  onResizeStop={(layout) =>
                    persist({
                      ...dashboard,
                      layouts: {
                        ...dashboard.layouts,
                        lg: layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
                      },
                    })
                  }
                >
                  {widgets.map((widget) => (
                    <div key={widget.id}>{renderWidget(widget)}</div>
                  ))}
                </GridLayout>
              ) : (
                <div className="mobile-grid">
                  {widgets.map((widget) => (
                    <div
                      key={widget.id}
                      className={widget.type === "metric" ? "mobile-metric" : "mobile-chart"}
                    >
                      {renderWidget(widget)}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <footer className="dashboard-bottom">
              <span>
                <Database size={12} />
                {synthetic
                  ? "Demonstração · dados sintéticos"
                  : "Fonte: ANTT · Rodovias federais concedidas"}
              </span>
              <span>Investigue com contexto. Decida com evidências.</span>
            </footer>
          </main>
          {showChat && (
            <div className={`chat-container mobile-${mobileTab}`}>
              <InvestigationChat
                messages={view?.session.messages ?? []}
                stages={stages}
                busy={busy}
                unavailable={unavailable}
                suggestions={suggestions}
                onSubmit={(message) => void send(message)}
                onCancel={() => abort.current?.abort()}
                onNew={() => void newSession()}
              />
            </div>
          )}
        </div>
        <div className="mobile-tabs">
          <button
            className={mobileTab === "dashboard" ? "active" : ""}
            onClick={() => setMobileTab("dashboard")}
          >
            <LayoutDashboard size={17} />
            Painel
          </button>
          <button
            className={mobileTab === "chat" ? "active" : ""}
            onClick={() => {
              setMobileTab("chat");
              setShowChat(true);
            }}
          >
            <Sparkles size={17} />
            Investigar
          </button>
        </div>
      </div>
    </MotionConfig>
  );
}
function InfoIcon() {
  return <ArrowDownToLine size={13} />;
}
