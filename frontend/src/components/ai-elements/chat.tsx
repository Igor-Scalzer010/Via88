"use client";
// Presentational AI Elements pattern: backend stages drive Trace, not model reasoning.
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Check, ChevronDown, LoaderCircle, Plus, Sparkles, Square } from "lucide-react";
import type { Session, Stage } from "@/lib/contracts.generated";
import { Button } from "@/components/ui/button";
function MessageText({ content }: { content: string }) {
  // Evidence summaries support emphasis as text; raw HTML is never interpreted.
  return (
    <p>
      {content
        .split(/(\*\*[^*]+\*\*)/g)
        .map((part, index) =>
          part.startsWith("**") && part.endsWith("**") ? (
            <strong key={index}>{part.slice(2, -2)}</strong>
          ) : (
            part
          ),
        )}
    </p>
  );
}
export function InvestigationChat({
  messages,
  stages,
  busy,
  unavailable,
  suggestions,
  onSubmit,
  onCancel,
  onNew,
}: {
  messages: Session["messages"];
  stages: Stage[];
  busy: boolean;
  unavailable: string;
  suggestions: string[];
  onSubmit: (message: string) => void;
  onCancel: () => void;
  onNew: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "auto", block: "nearest" });
  }, [messages.length, stages.length]);
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (prompt.trim() && !busy && !unavailable) {
      onSubmit(prompt.trim());
      setPrompt("");
    }
  }
  const defaults = [
    "Quais rodovias tiveram mais acidentes no último ano disponível?",
    "Como os acidentes evoluíram ao longo do tempo?",
    "Quais tipos de acidente foram mais frequentes?",
  ];
  return (
    <aside className="chat-panel" aria-label="Investigação com assistente">
      <header className="chat-heading">
        <div className="chat-symbol">
          <Sparkles size={18} />
        </div>
        <div>
          <h2>Explore com a Via</h2>
          <span>Uma pergunta, novas perspectivas</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNew}
          disabled={busy}
          aria-label="Nova investigação"
        >
          <Plus size={18} />
        </Button>
      </header>
      <div
        className="chat-conversation"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {!messages.length && (
          <div className="chat-welcome">
            <span className="welcome-symbol">
              <Sparkles size={25} />
            </span>
            <h3>
              Encontre a próxima
              <br />
              pergunta.
            </h3>
            <p>Investigue padrões, compare rodovias e aprofunde seus resultados em uma conversa.</p>
            <span className="eyebrow">COMECE POR AQUI</span>
            <div className="suggestions">
              {defaults.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => onSubmit(suggestion)}
                  disabled={busy || !!unavailable}
                >
                  {suggestion}
                  <ArrowUp size={13} />
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message) => (
          <article key={message.id} className={`chat-message message-${message.role}`}>
            <span className="message-author">
              {message.role === "user" ? (
                "Você"
              ) : (
                <>
                  <Sparkles size={12} />
                  Via
                </>
              )}
            </span>
            <MessageText content={message.content} />
          </article>
        ))}
        {busy && (
          <details className="trace" open>
            <summary>
              <LoaderCircle size={14} className="spin" />
              Análise em andamento
              <ChevronDown size={14} />
            </summary>
            <ol>
              {stages.map((stage, index) => (
                <li key={`${stage.stage}-${index}`}>
                  {index === stages.length - 1 ? (
                    <span className="stage-dot" />
                  ) : (
                    <Check size={12} />
                  )}
                  <span>{stage.label}</span>
                </li>
              ))}
            </ol>
          </details>
        )}
        {!busy && !!messages.length && !!suggestions.length && (
          <div className="followup-suggestions">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                disabled={!!unavailable}
                onClick={() => onSubmit(suggestion)}
              >
                {suggestion}
                <ArrowUp size={12} />
              </button>
            ))}
          </div>
        )}
        <div ref={bottom} />
      </div>
      <div className="chat-composer-wrap">
        {unavailable && <p className="chat-unavailable">{unavailable}</p>}
        <form className="chat-composer" onSubmit={submit}>
          <label htmlFor="question" className="sr-only">
            Pergunte sobre os dados
          </label>
          <textarea
            id="question"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            disabled={!!unavailable || busy}
            placeholder="O que você quer descobrir?"
            maxLength={4000}
            rows={2}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <div className="composer-bottom">
            <span>Dados reais. Respostas com evidências.</span>
            {busy ? (
              <Button
                type="button"
                size="icon"
                variant="outline"
                onClick={onCancel}
                aria-label="Interromper análise"
              >
                <Square size={13} />
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon"
                aria-label="Enviar pergunta"
                disabled={!prompt.trim() || !!unavailable}
              >
                <ArrowUp size={17} />
              </Button>
            )}
          </div>
        </form>
        <p className="chat-footnote">A Via informa quando os dados não são suficientes.</p>
      </div>
    </aside>
  );
}
