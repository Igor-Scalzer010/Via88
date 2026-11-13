"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSourceSpecification,
  type ExpressionSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Dataset } from "@/lib/contracts.generated";
import { number } from "@/lib/utils";
export default function GeoMap({
  dataset,
  xField,
  yField,
  onSelect,
}: {
  dataset: Dataset;
  xField: string;
  yField: string;
  onSelect: (uf: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const selection = useRef(onSelect);
  useEffect(() => {
    selection.current = onSelect;
  }, [onSelect]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!container.current) return;
    const controller = new AbortController();
    let map: maplibregl.Map | undefined;
    void fetch("/api/geography", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("A malha geográfica está indisponível.");
        const geo: unknown = await response.json();
        if (
          !geo ||
          typeof geo !== "object" ||
          !("type" in geo) ||
          geo.type !== "FeatureCollection" ||
          !("features" in geo) ||
          !Array.isArray(geo.features) ||
          !geo.features.length
        )
          throw new Error("A malha de UFs ainda não foi importada.");
        if (!container.current || controller.signal.aborted) return;
        // UF polygons convey regional totals; no accident coordinates are inferred.
        map = new maplibregl.Map({
          container: container.current,
          style: {
            version: 8,
            sources: {
              states: {
                type: "geojson",
                data: geo as GeoJSONSourceSpecification["data"],
                attribution: "Malha de UFs: IBGE · Acidentes: ANTT",
              },
            },
            layers: [
              { id: "background", type: "background", paint: { "background-color": "#eff5f9" } },
            ],
          },
          bounds: [
            [-74, -34],
            [-34, 6],
          ],
          fitBoundsOptions: { padding: 24, animate: false },
          attributionControl: { compact: true },
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
        map.on("load", () => {
          if (!map) return;
          const getUF: ExpressionSpecification = [
            "coalesce",
            ["get", "uf"],
            ["get", "sigla"],
            ["get", "SIGLA_UF"],
            "",
          ];
          const maximum = Math.max(1, ...dataset.rows.map((row) => Number(row[yField] ?? 0)));
          const colors: (string | number | ExpressionSpecification)[] = [];
          for (const row of dataset.rows) {
            const value = row[yField];
            if (typeof value === "number")
              colors.push(String(row[xField]), `hsl(204, 75%, ${90 - (value / maximum) * 52}%)`);
          }
          const fill = colors.length
            ? (["match", getUF, ...colors, "#e0e8ee"] as ExpressionSpecification)
            : "#e0e8ee";
          map.addLayer({
            id: "states-fill",
            type: "fill",
            source: "states",
            paint: { "fill-color": fill, "fill-opacity": 0.95 },
          });
          map.addLayer({
            id: "states-line",
            type: "line",
            source: "states",
            paint: { "line-color": "#ffffff", "line-width": 1 },
          });
          map.on("click", "states-fill", (event) => {
            const properties = event.features?.[0]?.properties;
            const uf: unknown = properties?.uf ?? properties?.sigla ?? properties?.SIGLA_UF;
            if (typeof uf === "string") selection.current(uf);
          });
          map.on("mouseenter", "states-fill", () => {
            if (map) map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", "states-fill", () => {
            if (map) map.getCanvas().style.cursor = "";
          });
        });
        const observer = new ResizeObserver(() => map?.resize());
        observer.observe(container.current);
        controller.signal.addEventListener("abort", () => observer.disconnect(), { once: true });
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : "Mapa indisponível.");
      });
    return () => {
      controller.abort();
      map?.remove();
    };
  }, [dataset, xField, yField]);
  return (
    <div className="map-widget">
      <div
        ref={container}
        className="map-canvas"
        aria-label="Mapa dos totais de acidentes por estado"
      />
      {error && (
        <div className="map-fallback">
          <p>{error}</p>
          <span>Totais por UF disponíveis na tabela.</span>
        </div>
      )}
      <span className="map-caption">Totais por UF · sem localização pontual</span>
      <div className="map-legend">
        <span>Cinza: sem informação</span>
        <span>Menor</span>
        <i />
        <span>
          Maior ·{" "}
          {number.format(Math.max(0, ...dataset.rows.map((row) => Number(row[yField] ?? 0))))}
        </span>
      </div>
    </div>
  );
}
