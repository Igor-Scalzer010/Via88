"use client";

import type { EChartsOption, EChartsType } from "echarts";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

/*
 * Adapted from <sb-echarts> in zweiundeins/starbase, itself ported from Libretto's <tco-chart>.
 * https://github.com/zweiundeins/starbase/blob/main/components/echarts/echarts.js
 *
 * MIT License
 * Copyright (c) 2026 zwei und eins gmbh and starbase contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

type Options = Record<string, unknown>;
type KindOption = Options & { kind: string };
type EChartsLibrary = typeof import("echarts");

interface KindContext {
  echarts: EChartsLibrary;
  color: (value: string) => string;
  css: (token: string) => string;
  formatNumber: (value: unknown) => string;
  lang: string;
  readonly width: number;
  readonly height: number;
}

type KindBuilder = (option: KindOption, context: KindContext) => EChartsOption | Options;

interface Registry {
  kinds: Map<string, KindBuilder>;
  charts: Set<(name: string) => void>;
  format?: (value: number, lang?: string) => string;
}

const registryKey = Symbol.for("sb-echarts-react");
const registry: Registry = ((globalThis as typeof globalThis & { [registryKey]?: Registry })[
  registryKey
] ??= { kinds: new Map(), charts: new Set() });

export function defineChartKind(name: string, build: KindBuilder) {
  registry.kinds.set(name, build);
  registry.charts.forEach((redraw) => redraw(name));
}

export function setNumberFormat(format: Registry["format"]) {
  registry.format = format;
}

let library: Promise<EChartsLibrary> | undefined;
const load = () =>
  (library ??= import("echarts").catch((error: unknown) => {
    library = undefined;
    throw error;
  }));

function isObject(value: unknown): value is Options {
  if (value === null || typeof value !== "object") return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

const list = (value: unknown): unknown[] => [value].flat();
const missing = (value: unknown) => value == null || value === "-" || Number.isNaN(value);
const escapeHTML = (value: unknown) =>
  String(value).replace(/[&<>"']/g, (character) => `&#${character.charCodeAt(0)};`);

// ECharts puts the axis tooltip's value in the dimension encoded on the other axis.
const valueAxes = new Map([
  ["x", "y"],
  ["y", "x"],
  ["angle", "radius"],
  ["radius", "angle"],
]);

function tooltipValue(point: Options) {
  const { value, encode, axisDim, dimensionNames } = point;
  const axis = valueAxes.get(String(axisDim));
  const dimensions = axis && isObject(encode) ? encode[axis] : undefined;
  const index = Array.isArray(dimensions) ? dimensions.at(-1) : undefined;
  if (Array.isArray(value)) return value[index ?? value.length - 1];
  if (isObject(value) && Array.isArray(dimensionNames)) return value[dimensionNames[index]];
  return value;
}

function axisTooltip(params: unknown, format: (value: unknown) => string, series: unknown[]) {
  const rows = list(params)
    .filter(isObject)
    .map((point) => ({ point, value: tooltipValue(point) }))
    .filter(({ value }) => !missing(value));
  if (!rows.length) return "";

  const content = rows.map(({ point, value }) => {
    const source = series[Number(point.seriesIndex)];
    const tooltip = isObject(source) && isObject(source.tooltip) ? source.tooltip : undefined;
    const valueFormat = tooltip?.valueFormatter;
    const formatted = typeof valueFormat === "function" ? valueFormat(value) : format(value);
    const marker = typeof point.marker === "string" ? point.marker : "";
    return (
      `<div style="margin:10px 0 0;line-height:1">${marker}<span style="margin-left:2px">${escapeHTML(point.seriesName ?? "")}</span>` +
      `<span style="float:right;margin-left:20px;font-weight:700">${escapeHTML(formatted)}</span><div style="clear:both"></div></div>`
    );
  });
  return `<div style="line-height:1;opacity:.72">${escapeHTML(rows[0].point.axisValueLabel ?? "")}</div>${content.join("")}`;
}

// Plain objects merge recursively so a caller can override a single theme property.
function deepMerge(base: Options, overrides: object): Options {
  const additions = Object.entries(overrides).map(([key, value]) => {
    const previous = base[key];
    return [key, isObject(previous) && isObject(value) ? deepMerge(previous, value) : value];
  });
  return { ...base, ...Object.fromEntries(additions) };
}

function locale(tag?: string) {
  try {
    return Intl.getCanonicalLocales(tag?.replace(/_/g, "-") || [])[0];
  } catch {
    return undefined;
  }
}

const locales = new Set<string>();

function localeFor(echarts: EChartsLibrary, lang: string) {
  const code = `sb-${lang}`;
  if (locales.has(code)) return code;

  const format = (options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(lang, { ...options, timeZone: "UTC" }).format;
  const months = Array.from({ length: 12 }, (_, month) => Date.UTC(2024, month, 1));
  const days = Array.from({ length: 7 }, (_, day) => Date.UTC(2024, 0, 7 + day));
  // ECharts fills sections omitted from a registered locale from its English locale.
  const time = {
    month: months.map(format({ month: "long" })),
    monthAbbr: months.map(format({ month: "short" })),
    dayOfWeek: days.map(format({ weekday: "long" })),
    dayOfWeekAbbr: days.map(format({ weekday: "short" })),
  };
  echarts.registerLocale(code, { time } as Parameters<EChartsLibrary["registerLocale"]>[1]);
  locales.add(code);
  return code;
}

let pixelContext: CanvasRenderingContext2D | null = null;

// Convert CSS colors such as oklch() and color-mix() to sRGB for ECharts.
function rgba(css: string) {
  pixelContext ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!pixelContext) return css;

  pixelContext.clearRect(0, 0, 1, 1);
  pixelContext.fillStyle = "#000";
  pixelContext.fillStyle = css;
  pixelContext.fillRect(0, 0, 1, 1);
  const [red, green, blue, alpha] = pixelContext.getImageData(0, 0, 1, 1).data;
  return alpha === 255
    ? `rgb(${red}, ${green}, ${blue})`
    : `rgba(${red}, ${green}, ${blue}, ${+(alpha / 255).toFixed(3)})`;
}

const palette = Array.from({ length: 8 }, (_, index) => `--_c${index + 1}`);
const keyboardSteps = new Map<string, [number, number]>([
  ["ArrowRight", [0, 1]],
  ["ArrowLeft", [0, -1]],
  ["ArrowDown", [1, 0]],
  ["ArrowUp", [-1, 0]],
  ["Enter", [0, 0]],
]);
const clamp = (value: number, max: number) => Math.max(0, Math.min(value, max));

interface ChartClick {
  seriesName?: string;
  seriesIndex?: number;
  name?: string;
  value?: unknown;
  dataIndex?: number;
}

// The keyboard adapter needs the resolved series data, including items sourced from a dataset.
interface KeyboardModel {
  getSeriesCount(): number;
  getSeriesByIndex(index: number): {
    getData(): { count(): number; getRawIndex(index: number): number };
    getDataParams(index: number): ChartClick;
  };
}

export interface EChartsProps {
  /** ECharts options. A value of the form var(--token) is resolved from the chart host. */
  option?: EChartsOption | Options | null;
  renderer?: "canvas" | "svg";
  /** Defaults to the closest element's lang attribute, then the browser's language. */
  lang?: string;
  onChartClick?: (detail: ChartClick) => void;
  className?: string;
  style?: CSSProperties;
  /** Shown until the chart draws and retained for assistive technology afterwards. */
  children?: ReactNode;
}

/** Draw an ECharts option, or expand a registered kind, using the page's theme. */
export default function EChart({
  option = null,
  renderer = "canvas",
  lang,
  onChartClick,
  className,
  style,
  children,
}: EChartsProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const hasFallback = children != null;
  const settings = useRef({ option, renderer, lang, onChartClick, hasFallback });
  const api = useRef<{ redraw: () => void; restart: () => void } | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    const plot = plotRef.current;
    if (!host || !plot) return;

    let alive = true;
    let visible = false;
    let starting = false;
    let echarts: EChartsLibrary;
    let chart: EChartsType | undefined;
    let unfitted: { option: Options; grid: Options } | undefined;
    let fitted: string | undefined;
    let measure: CanvasRenderingContext2D | null = null;
    let sized = false;
    let seriesIndex = 0;
    let itemIndex = -1;

    const scheme = matchMedia("(prefers-color-scheme: dark)");
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const langOf = () =>
      locale(settings.current.lang || host.closest("[lang]")?.getAttribute("lang") || undefined) ??
      navigator.language;
    const css = (token: string) => getComputedStyle(host).getPropertyValue(token).trim();
    const font = () => css("--_font") || getComputedStyle(host).fontFamily;
    const color = (value: string) => {
      const probe = document.createElement("span");
      probe.style.color = value.startsWith("--") ? `var(${value})` : value;
      host.append(probe);
      const computed = getComputedStyle(probe).color;
      probe.remove();
      return rgba(computed);
    };

    const resolveVars = (value: unknown): unknown => {
      if (typeof value === "string" && /^var\(--[\w-]+\)$/.test(value)) return color(value);
      if (Array.isArray(value)) return value.map(resolveVars);
      if (isObject(value)) {
        return Object.fromEntries(
          Object.entries(value).map(([key, item]) => [key, resolveVars(item)]),
        );
      }
      return value;
    };

    /** Apply theme defaults while preserving caller formatters and styles. */
    const build = (input: EChartsOption | Options): Options | undefined => {
      const language = langOf();
      const number = new Intl.NumberFormat(language, { maximumFractionDigits: 20 });
      const formatNumber = (value: unknown) => {
        if (missing(value)) return "-";
        if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
        return registry.format?.(value, language) ?? number.format(value);
      };

      let option = input;
      if ("kind" in input && typeof input.kind === "string") {
        const kind = registry.kinds.get(input.kind);
        if (!kind) return;
        option = kind(
          { ...input, kind: input.kind },
          {
            echarts,
            color,
            css,
            formatNumber,
            lang: language,
            get width() {
              sized = true;
              return plot.clientWidth;
            },
            get height() {
              sized = true;
              return plot.clientHeight;
            },
          },
        );
      }
      const text = color("--_text");
      const muted = color("--_muted");
      const line = color("--_line");
      const fontFamily = font();
      const numbers = css("--_numbers") || fontFamily;
      const base: Options = {
        color: palette.map(color),
        backgroundColor: "transparent",
        animation: !motion.matches,
        animationDuration: 700,
        animationEasing: "cubicOut",
        animationDurationUpdate: 450,
        animationEasingUpdate: "cubicInOut",
        textStyle: { color: text, fontFamily },
        tooltip: {
          backgroundColor: color("--_tip"),
          borderColor: line,
          textStyle: { color: color("--_strong"), fontFamily: numbers, fontSize: 12 },
        },
        aria: { enabled: !settings.current.hasFallback },
      };
      if (option.xAxis || option.yAxis) {
        const axis = {
          axisLine: { lineStyle: { color: line } },
          axisTick: { lineStyle: { color: line } },
          axisLabel: { color: muted, fontFamily },
          splitLine: { lineStyle: { color: color("--_grid") } },
          nameTextStyle: { color: muted, fontFamily },
        };
        base.xAxis = axis;
        base.yAxis = { ...axis, axisLabel: { ...axis.axisLabel, fontFamily: numbers } };
        base.grid = { left: "3%", right: "4%", top: "10%", bottom: "12%" };
      }

      const themed = resolveVars(deepMerge(base, option)) as Options;
      if (themed.legend) {
        themed.legend = list(themed.legend).map((legend) =>
          isObject(legend)
            ? deepMerge({ textStyle: { color: muted, fontFamily } }, legend)
            : legend,
        );
      }
      const series = list(themed.series);
      for (const entry of series.filter(isObject)) {
        if (entry.type === "pie" || entry.type === "funnel") {
          entry.label = { color: text, textBorderWidth: 0, ...(entry.label as Options) };
        }
      }
      for (const [key, defaultType] of [
        ["xAxis", "category"],
        ["yAxis", "value"],
      ]) {
        const defaults = base[key];
        if (Array.isArray(themed[key]) && isObject(defaults)) {
          themed[key] = themed[key].map((axis) =>
            isObject(axis) ? deepMerge(defaults, axis) : axis,
          );
        }
        for (const axis of list(themed[key]).filter(isObject)) {
          if ((axis.type ?? defaultType) !== "value") continue;
          axis.axisLabel = { formatter: formatNumber, ...(axis.axisLabel as Options) };
        }
      }
      const ownTooltip = series.some(
        (entry) => isObject(entry) && /candle|box|^k$/.test(String(entry.type)),
      );
      for (const tooltip of list(themed.tooltip).filter(isObject)) {
        tooltip.valueFormatter ??= formatNumber;
        if (tooltip.trigger === "axis" && tooltip.renderMode !== "richText" && !ownTooltip) {
          const format = tooltip.valueFormatter as typeof formatNumber;
          tooltip.formatter ??= (params: unknown) => axisTooltip(params, format, series);
        }
      }
      return themed;
    };

    /** Reserve room below cartesian plots for a wrapped legend or horizontal slider. */
    const margins = (option: Options, grid: Options) => {
      let { top, bottom } = grid;
      const [legend] = list(option.legend);
      const { clientWidth: width, clientHeight: height } = plot;
      const pixels = (value: unknown) => {
        if (typeof value === "number") return value;
        const size = parseFloat(String(value)) || 0;
        return typeof value === "string" && value.endsWith("%") ? (height * size) / 100 : size;
      };
      const numeric = (value: unknown, fallback: number) =>
        typeof value === "number" ? value : fallback;
      if (
        isObject(legend) &&
        legend.show !== false &&
        (legend.orient ?? "horizontal") === "horizontal"
      ) {
        const labels = Array.isArray(legend.data)
          ? legend.data
          : list(option.series)
              .filter(isObject)
              .map((entry) => entry.name)
              .filter((name) => name != null);
        if (labels.length && width && height) {
          const near = (value: unknown) =>
            value === "0" ||
            (typeof value === "string" && value.endsWith("%") && parseFloat(value) < 25) ||
            (typeof value === "number" && value < 60);
          const atTop = legend.top === "top" || near(legend.top);
          const atBottom =
            legend.bottom === "bottom" ||
            near(legend.bottom) ||
            (legend.top == null && legend.bottom == null);
          measure ??= document.createElement("canvas").getContext("2d");
          let rows = 1;
          let used = 0;
          if (measure && legend.type !== "scroll") {
            measure.font = `12px ${font()}`;
            const spacing = numeric(legend.itemWidth, 25) + numeric(legend.itemGap, 10) + 5;
            for (const label of labels) {
              const size =
                spacing + measure.measureText(String(isObject(label) ? label.name : label)).width;
              if (used > 0 && used + size > width * 0.96) {
                rows++;
                used = 0;
              }
              used += size;
            }
          }
          const block = rows * 26 + 6;
          if (atTop && rows > 1) {
            const named = list(option.yAxis).some((axis) => isObject(axis) && axis.name);
            top = Math.max(pixels(top), numeric(legend.top, 8) + block + (named ? 28 : 0));
          }
          if (atBottom) bottom = Math.max(pixels(bottom), numeric(legend.bottom, 15) + block + 22);
        }
      }
      for (const zoom of list(option.dataZoom).filter(isObject)) {
        if (
          zoom.type === "slider" &&
          (zoom.orient ? zoom.orient === "horizontal" : zoom.yAxisIndex == null)
        ) {
          bottom = Math.max(pixels(bottom), pixels(zoom.bottom ?? 15) + 66);
        }
      }
      return { top, bottom };
    };

    const click = ({ seriesName, seriesIndex, name, value, dataIndex }: ChartClick) => {
      settings.current.onChartClick?.({ seriesName, seriesIndex, name, value, dataIndex });
    };

    const dispose = () => {
      chart?.dispose();
      chart = undefined;
      host.dataset.ready = "false";
    };

    const draw = (quiet = false) => {
      if (!chart) return;
      unfitted = undefined;
      sized = false;
      try {
        const current = settings.current.option;
        const option = current && build(current);
        if (!option) {
          chart.clear();
          host.dataset.ready = "false";
          return;
        }
        if (quiet || motion.matches) option.animation = false;
        if (option.xAxis && isObject(option.grid)) {
          unfitted = { option, grid: option.grid };
          const layout = margins(option, option.grid);
          fitted = JSON.stringify(layout);
          option.grid = { ...option.grid, ...layout };
        }
        chart.setOption(option, true);
        host.dataset.ready = "true";
      } catch (error) {
        dispose();
        console.error("<EChart>: ECharts cannot draw this option", error);
      }
    };

    const canStart = () =>
      alive &&
      !chart &&
      visible &&
      settings.current.option &&
      plot.clientWidth &&
      plot.clientHeight;

    const start = async () => {
      if (starting || !canStart()) return;
      starting = true;
      try {
        echarts = await load();
        if (!canStart()) return;
        chart = echarts.init(plot, undefined, {
          renderer: settings.current.renderer,
          locale: localeFor(echarts, langOf()),
        });
        chart.on("click", "series", click);
        draw();
      } catch (error) {
        dispose();
        console.error("<EChart>: ECharts could not start", error);
      } finally {
        starting = false;
      }
    };

    const retheme = () => draw(true);

    const resize = () => {
      if (!chart) {
        void start();
        return;
      }
      if (!plot.clientWidth || !plot.clientHeight) return;
      chart.resize();
      if (sized) {
        draw(true);
      } else if (unfitted) {
        const grid = margins(unfitted.option, unfitted.grid);
        const layout = JSON.stringify(grid);
        if (layout !== fitted) {
          fitted = layout;
          chart.setOption({ grid });
        }
      }
    };

    const onKey = (event: KeyboardEvent) => {
      const step = keyboardSteps.get(event.key);
      if (!chart || !step || host.dataset.ready !== "true") return;
      // ECharts keeps its model accessor private in the public TypeScript interface.
      const model = (chart as unknown as { getModel?: () => KeyboardModel }).getModel?.();
      const count = model?.getSeriesCount();
      if (!model || !count) return;
      const [seriesStep, itemStep] = step;
      if (!seriesStep && !itemStep && itemIndex < 0) return;

      seriesIndex = clamp(seriesIndex + seriesStep, count - 1);
      const series = model.getSeriesByIndex(seriesIndex);
      const data = series.getData();
      if (!data.count()) return;
      event.preventDefault();
      itemIndex = clamp(itemIndex + itemStep, data.count() - 1);
      if (seriesStep || itemStep) {
        chart.dispatchAction({
          type: "showTip",
          seriesIndex,
          dataIndex: data.getRawIndex(itemIndex),
        });
      } else {
        click(series.getDataParams(itemIndex));
      }
    };
    const onBlur = () => chart?.dispatchAction({ type: "hideTip" });

    const intersection = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        void start();
      },
      { rootMargin: "200px" },
    );
    const dimensions = new ResizeObserver(resize);
    const theme = new MutationObserver(retheme);
    intersection.observe(host);
    dimensions.observe(plot);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    plot.addEventListener("keydown", onKey);
    plot.addEventListener("blur", onBlur);
    scheme.addEventListener("change", retheme);
    motion.addEventListener("change", retheme);
    window.addEventListener("sb-theme-change", retheme);
    const onKind = (name: string) => {
      const current = settings.current.option;
      if (current && "kind" in current && current.kind === name) draw();
    };
    registry.charts.add(onKind);

    api.current = {
      redraw: () => (chart ? draw() : void start()),
      restart: () => {
        dispose();
        void start();
      },
    };

    return () => {
      alive = false;
      api.current = null;
      intersection.disconnect();
      dimensions.disconnect();
      theme.disconnect();
      plot.removeEventListener("keydown", onKey);
      plot.removeEventListener("blur", onBlur);
      scheme.removeEventListener("change", retheme);
      motion.removeEventListener("change", retheme);
      window.removeEventListener("sb-theme-change", retheme);
      registry.charts.delete(onKind);
      dispose();
    };
  }, []);

  useEffect(() => {
    const previous = settings.current;
    settings.current = { option, renderer, lang, onChartClick, hasFallback };
    if (previous.renderer !== renderer || previous.lang !== lang) {
      api.current?.restart();
    } else if (previous.option !== option || previous.hasFallback !== hasFallback) {
      api.current?.redraw();
    }
  }, [option, renderer, lang, onChartClick, hasFallback]);

  return (
    <div
      ref={hostRef}
      className={["sb-echarts", className].filter(Boolean).join(" ")}
      style={style}
      data-ready="false"
    >
      <div
        className="plot"
        ref={plotRef}
        tabIndex={hasFallback ? undefined : 0}
        aria-hidden={hasFallback || undefined}
      />
      {hasFallback && <div className="fallback">{children}</div>}
    </div>
  );
}
