import type { SampleRow } from "../types";
import { numericValue } from "../lib/telemetry";

const PA_PER_PSI = 6894.757293168;

export interface TelemetryPlotSpec {
  field: string;
  label: string;
  unit: string;
  color: string;
  convert: (value: number) => number;
}

export interface TelemetrySeriesPoint {
  time: number;
  value: number;
}

const BASE_PLOT_SPECS: TelemetryPlotSpec[] = [
  {
    field: "P",
    label: "Pressure vs time",
    unit: "psi",
    color: "#3b9dff",
    convert: (value) => value / PA_PER_PSI
  },
  {
    field: "T",
    label: "Temperature vs time",
    unit: "F",
    color: "#f59e0b",
    convert: (value) => ((value - 273.15) * 9) / 5 + 32
  },
  {
    field: "mdot",
    label: "Mass flow vs time",
    unit: "kg/s",
    color: "#34d399",
    convert: (value) => value
  }
];

const ENGINE_FLOW_SPECS: TelemetryPlotSpec[] = [
  {
    field: "mdot_ox",
    label: "Oxidizer flow vs time",
    unit: "kg/s",
    color: "#0ea5e9",
    convert: (value) => value
  },
  {
    field: "mdot_fu",
    label: "Fuel flow vs time",
    unit: "kg/s",
    color: "#c97706",
    convert: (value) => value
  }
];

function hasNumericField(rows: SampleRow[], field: string): boolean {
  return rows.some((row) => typeof row[field] === "number" && Number.isFinite(row[field]));
}

export function telemetryPlotSpecsForRows(rows: SampleRow[]): TelemetryPlotSpec[] {
  const specs = BASE_PLOT_SPECS.filter((spec) => hasNumericField(rows, spec.field));
  if (!hasNumericField(rows, "mdot")) {
    specs.push(...ENGINE_FLOW_SPECS.filter((spec) => hasNumericField(rows, spec.field)));
  }
  return specs;
}

export function telemetrySeries(rows: SampleRow[], spec: TelemetryPlotSpec): TelemetrySeriesPoint[] {
  return [...rows]
    .sort((a, b) => a.time - b.time)
    .flatMap((row) => {
      const value = numericValue(row, spec.field);
      return value === undefined ? [] : [{ time: row.time, value: spec.convert(value) }];
    });
}

function formatPlotValue(value: number | undefined): string {
  if (value === undefined) return "n/a";
  if (Math.abs(value) >= 10000 || (Math.abs(value) > 0 && Math.abs(value) < 0.01)) return value.toExponential(3);
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function plotPath(points: TelemetrySeriesPoint[], currentTime: number) {
  const width = 260;
  const height = 92;
  const padding = { top: 12, right: 12, bottom: 20, left: 34 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const times = points.map((point) => point.time);
  const values = points.map((point) => point.value);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const timeSpan = maxTime - minTime || 1;
  const valueSpan = maxValue - minValue || Math.max(Math.abs(maxValue) * 0.1, 1);
  const paddedMinValue = minValue === maxValue ? minValue - valueSpan / 2 : minValue;
  const paddedMaxValue = minValue === maxValue ? maxValue + valueSpan / 2 : maxValue;
  const paddedValueSpan = paddedMaxValue - paddedMinValue || 1;

  const xForTime = (time: number) => padding.left + ((time - minTime) / timeSpan) * chartWidth;
  const yForValue = (value: number) =>
    padding.top + (1 - (value - paddedMinValue) / paddedValueSpan) * chartHeight;

  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xForTime(point.time).toFixed(2)} ${yForValue(point.value).toFixed(2)}`)
    .join(" ");
  const cursorX = Math.max(padding.left, Math.min(padding.left + chartWidth, xForTime(currentTime)));

  return {
    width,
    height,
    path,
    cursorX,
    minTime,
    maxTime,
    minValue: paddedMinValue,
    maxValue: paddedMaxValue,
    chartTop: padding.top,
    chartBottom: padding.top + chartHeight,
    chartLeft: padding.left,
    chartRight: padding.left + chartWidth
  };
}

export function TelemetryPlots({
  rows,
  currentSample,
  time
}: {
  rows: SampleRow[] | undefined;
  currentSample: SampleRow | undefined;
  time: number;
}) {
  const safeRows = rows ?? [];
  const specs = telemetryPlotSpecsForRows(safeRows);
  if (safeRows.length === 0 || specs.length === 0) {
    return <div className="inspector-empty">Click a node or connection in the P&amp;ID to inspect its telemetry.</div>;
  }

  return (
    <div className="telemetry-plots">
      {specs.map((spec) => {
        const series = telemetrySeries(safeRows, spec);
        if (series.length === 0) return null;
        const chart = plotPath(series, time);
        const currentValue = numericValue(currentSample, spec.field);
        const convertedCurrent = currentValue === undefined ? undefined : spec.convert(currentValue);

        return (
          <section key={spec.field} className="telemetry-plot-card" aria-label={spec.label}>
            <div className="telemetry-plot-head">
              <span>{spec.label}</span>
              <strong>
                {formatPlotValue(convertedCurrent)} <small>{spec.unit}</small>
              </strong>
            </div>
            <svg
              className="telemetry-plot"
              viewBox={`0 0 ${chart.width} ${chart.height}`}
              role="img"
              aria-label={`${spec.label}, current value ${formatPlotValue(convertedCurrent)} ${spec.unit}`}
            >
              <line className="telemetry-grid-line" x1={chart.chartLeft} y1={chart.chartTop} x2={chart.chartRight} y2={chart.chartTop} />
              <line className="telemetry-grid-line" x1={chart.chartLeft} y1={chart.chartBottom} x2={chart.chartRight} y2={chart.chartBottom} />
              <line className="telemetry-cursor" x1={chart.cursorX} y1={chart.chartTop} x2={chart.cursorX} y2={chart.chartBottom} />
              <path className="telemetry-line" d={chart.path} stroke={spec.color} />
              {series.length === 1 && (
                <circle
                  className="telemetry-point"
                  cx={chart.cursorX}
                  cy={(chart.chartTop + chart.chartBottom) / 2}
                  r={3}
                  fill={spec.color}
                />
              )}
              <text x={chart.chartLeft} y={chart.height - 5} className="telemetry-axis-label">
                {formatPlotValue(chart.minTime)}s
              </text>
              <text x={chart.chartRight} y={chart.height - 5} textAnchor="end" className="telemetry-axis-label">
                {formatPlotValue(chart.maxTime)}s
              </text>
              <text x={chart.chartLeft - 6} y={chart.chartTop + 4} textAnchor="end" className="telemetry-axis-label">
                {formatPlotValue(chart.maxValue)}
              </text>
              <text x={chart.chartLeft - 6} y={chart.chartBottom + 3} textAnchor="end" className="telemetry-axis-label">
                {formatPlotValue(chart.minValue)}
              </text>
            </svg>
          </section>
        );
      })}
    </div>
  );
}
