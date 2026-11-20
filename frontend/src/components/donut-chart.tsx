import type { EChartsOption } from "echarts";
import { useMemo } from "react";
import type { Dataset } from "@/lib/contracts.generated";
import { number } from "@/lib/utils";
import EChart from "@/components/ui/echarts";

export function DonutChart({
  data,
  labelField,
  valueField,
  valueLabel,
  title,
}: {
  data: Dataset["rows"];
  labelField: string;
  valueField: string;
  valueLabel: string;
  title: string;
}) {
  const { slices, option } = useMemo(() => {
    const slices = data.flatMap((row) => {
      const value = row[valueField];
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return [];
      const name = String(row[labelField] ?? "Sem classificação");
      return [{ id: String(row.key ?? name), name, value }];
    });
    const option: EChartsOption | null = slices.some(({ value }) => value > 0)
      ? {
          tooltip: {
            trigger: "item",
            confine: true,
            valueFormatter: (value) => (typeof value === "number" ? number.format(value) : "—"),
          },
          series: [
            {
              name: valueLabel,
              type: "pie",
              radius: ["51%", "80%"],
              padAngle: 3,
              label: { show: false },
              labelLine: { show: false },
              data: slices,
            },
          ],
        }
      : null;
    return { slices, option };
  }, [data, labelField, valueField, valueLabel]);

  return (
    <EChart option={option}>
      {option ? (
        <table className="w-full text-left text-xs">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">Categoria</th>
              <th scope="col" className="text-right">
                {valueLabel}
              </th>
            </tr>
          </thead>
          <tbody>
            {slices.map(({ id, name, value }) => (
              <tr key={id}>
                <th scope="row" className="py-1 font-normal">
                  {name}
                </th>
                <td className="text-right tabular-nums">{number.format(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="grid h-full place-items-center text-xs muted">
          Nenhum valor positivo para exibir.
        </p>
      )}
    </EChart>
  );
}
