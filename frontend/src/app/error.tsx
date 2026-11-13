"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="app-error">
      <h1>Não foi possível abrir este espaço.</h1>
      <p>Seus resultados salvos continuam disponíveis no servidor.</p>
      <button className="button" onClick={reset}>
        Tentar novamente
      </button>
    </main>
  );
}
