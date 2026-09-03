"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";
import type { MouseHandlerDataParam } from "recharts";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const FORECAST_HORIZON_HOURS = 72;
const TIME_ZONE = "Europe/Brussels";

type City = {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
};

type ForecastPoint = {
  target_time: string;
  temperature_2m: number;
  wind_speed_10m: number;
  forecast_run_at: string;
};

type LatestForecastResponse = {
  city_id: number;
  city_name: string;
  forecasts: ForecastPoint[];
};

type HistoryPoint = {
  forecast_run_at: string;
  temperature_2m: number;
  wind_speed_10m: number;
};

type ForecastHistoryResponse = {
  city_id: number;
  target_time: string;
  history: HistoryPoint[];
};

const chartConfig = {
  temperature_2m: {
    label: "Temperatuur (°C)",
    color: "oklch(0.52 0.12 245)",
  },
  wind_speed_10m: {
    label: "Windsnelheid (km/h)",
    color: "oklch(0.64 0.14 55)",
  },
} satisfies ChartConfig;

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new Error(
      `Backend niet bereikbaar op ${API_BASE}. Controleer of de API draait.`,
    );
  }

  if (!response.ok) {
    throw new Error(`De API gaf HTTP ${response.status} terug.`);
  }

  try {
    return (await response.json()) as T;
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new Error("De API-respons kon niet worden gelezen.");
  }
}

function formatDateTime(
  iso: string,
  options: Intl.DateTimeFormatOptions,
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat("nl-BE", {
    timeZone: TIME_ZONE,
    ...options,
  }).format(date);
}

function formatHourTick(iso: string): string {
  return formatDateTime(iso, {
    weekday: "short",
    hour: "2-digit",
  });
}

function formatFullDateTime(iso: string): string {
  return formatDateTime(iso, {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRunTick(iso: string): string {
  return formatDateTime(iso, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function takeHorizon(
  points: ForecastPoint[],
  hours: number,
): ForecastPoint[] {
  const cutoff = Date.now() + hours * 60 * 60 * 1000;
  return points.filter((point) => {
    const timestamp = new Date(point.target_time).getTime();
    return !Number.isNaN(timestamp) && timestamp <= cutoff;
  });
}

function selectTargetTime(
  state: MouseHandlerDataParam,
  points: ForecastPoint[],
): string | null {
  if (typeof state.activeLabel === "string" && state.activeLabel.length > 0) {
    return state.activeLabel;
  }
  const index = Number(state.activeIndex);
  if (Number.isInteger(index) && points[index]) {
    return points[index].target_time;
  }
  return null;
}

function Feedback({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 px-6 text-center">
      <AlertCircle className="size-5 text-muted-foreground" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 text-muted-foreground">
      <Loader2 className="size-5 animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export default function Home() {
  const [cities, setCities] = useState<City[]>([]);
  const [citiesLoading, setCitiesLoading] = useState(true);
  const [citiesError, setCitiesError] = useState<string | null>(null);
  const [citiesRetry, setCitiesRetry] = useState(0);

  const [selectedCityId, setSelectedCityId] = useState<number | null>(null);

  const [forecasts, setForecasts] = useState<ForecastPoint[]>([]);
  const [forecastCityName, setForecastCityName] = useState<string | null>(null);
  const [forecastRunAt, setForecastRunAt] = useState<string | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [forecastRetry, setForecastRetry] = useState(0);

  const [selectedTargetTime, setSelectedTargetTime] = useState<string | null>(
    null,
  );
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyRetry, setHistoryRetry] = useState(0);
  const hoveredTargetTime = useRef<string | null>(null);

  const selectedCity = cities.find((city) => city.id === selectedCityId);
  const cityItems = useMemo(
    () =>
      cities.map((city) => ({
        value: String(city.id),
        label: city.name,
      })),
    [cities],
  );

  useEffect(() => {
    const controller = new AbortController();

    async function loadCities() {
      setCitiesLoading(true);
      setCitiesError(null);
      try {
        const data = await apiGet<City[]>("/api/v1/cities", controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        setCities(data);
        setSelectedCityId((current) => {
          if (current !== null && data.some((city) => city.id === current)) {
            return current;
          }
          return data[0]?.id ?? null;
        });
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) {
          return;
        }
        setCities([]);
        setSelectedCityId(null);
        setForecasts([]);
        setForecastCityName(null);
        setForecastRunAt(null);
        setSelectedTargetTime(null);
        setHistory([]);
        setCitiesError(
          errorMessage(error, "Steden konden niet worden opgehaald."),
        );
      } finally {
        if (!controller.signal.aborted) {
          setCitiesLoading(false);
        }
      }
    }

    void loadCities();
    return () => controller.abort();
  }, [citiesRetry]);

  useEffect(() => {
    if (selectedCityId === null) {
      return;
    }

    const controller = new AbortController();
    const cityId = selectedCityId;

    async function loadForecast() {
      setForecastLoading(true);
      setForecastError(null);
      setSelectedTargetTime(null);
      hoveredTargetTime.current = null;
      setHistory([]);
      setHistoryError(null);
      try {
        const data = await apiGet<LatestForecastResponse>(
          `/api/v1/forecasts/latest?city_id=${cityId}`,
          controller.signal,
        );
        if (controller.signal.aborted) {
          return;
        }
        const horizon = takeHorizon(data.forecasts, FORECAST_HORIZON_HOURS);
        setForecasts(horizon);
        setForecastCityName(data.city_name);
        setForecastRunAt(horizon[0]?.forecast_run_at ?? null);
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) {
          return;
        }
        setForecasts([]);
        setForecastCityName(null);
        setForecastRunAt(null);
        setForecastError(
          errorMessage(error, "Laatste voorspelling kon niet worden opgehaald."),
        );
      } finally {
        if (!controller.signal.aborted) {
          setForecastLoading(false);
        }
      }
    }

    void loadForecast();
    return () => controller.abort();
  }, [selectedCityId, forecastRetry]);

  useEffect(() => {
    if (selectedCityId === null || selectedTargetTime === null) {
      return;
    }

    const controller = new AbortController();
    const cityId = selectedCityId;
    const targetTime = selectedTargetTime;

    async function loadHistory() {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        const params = new URLSearchParams({
          city_id: String(cityId),
          target_time: targetTime,
        });
        const data = await apiGet<ForecastHistoryResponse>(
          `/api/v1/forecasts/history?${params.toString()}`,
          controller.signal,
        );
        if (controller.signal.aborted) {
          return;
        }
        setHistory(data.history);
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) {
          return;
        }
        setHistory([]);
        setHistoryError(
          errorMessage(error, "Revisiegeschiedenis kon niet worden opgehaald."),
        );
      } finally {
        if (!controller.signal.aborted) {
          setHistoryLoading(false);
        }
      }
    }

    void loadHistory();
    return () => controller.abort();
  }, [selectedCityId, selectedTargetTime, historyRetry]);

  const handleCityChange = useCallback((value: string | null) => {
    if (value == null) {
      return;
    }
    const nextId = Number(value);
    if (!Number.isFinite(nextId)) {
      return;
    }
    hoveredTargetTime.current = null;
    setSelectedTargetTime(null);
    setHistory([]);
    setSelectedCityId(nextId);
  }, []);

  const handleForecastHover = useCallback(
    (state: MouseHandlerDataParam) => {
      hoveredTargetTime.current = selectTargetTime(state, forecasts);
    },
    [forecasts],
  );

  const handleForecastClick = useCallback(
    (state: MouseHandlerDataParam) => {
      const targetTime =
        hoveredTargetTime.current ?? selectTargetTime(state, forecasts);
      if (targetTime) {
        setSelectedTargetTime(targetTime);
      }
    },
    [forecasts],
  );

  return (
    <div className="flex min-h-full flex-col bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">
            Belgian Weather Explorer
          </h1>
          <Select
            value={selectedCityId === null ? null : String(selectedCityId)}
            onValueChange={handleCityChange}
            items={cityItems}
            disabled={citiesLoading || cities.length === 0}
          >
            <SelectTrigger className="w-[180px]" size="default">
              <SelectValue placeholder="Kies een stad" />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} align="end">
              {cityItems.map((city) => (
                <SelectItem key={city.value} value={city.value}>
                  {city.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-6">
        {citiesError ? (
          <Card>
            <Feedback
              title="Backend niet bereikbaar"
              description={citiesError}
              action={
                <Button
                  variant="outline"
                  onClick={() => setCitiesRetry((value) => value + 1)}
                >
                  Opnieuw proberen
                </Button>
              }
            />
          </Card>
        ) : null}

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Latest Forecast</CardTitle>
            <CardDescription>
              {forecastCityName
                ? `${FORECAST_HORIZON_HOURS} uur vooruit voor ${forecastCityName}. Klik op een uur om de revisiegeschiedenis te openen.`
                : `Voorspelling voor de komende ${FORECAST_HORIZON_HOURS} uur. Klik op een uur om de revisiegeschiedenis te openen.`}
              {forecastRunAt
                ? ` Run: ${formatFullDateTime(forecastRunAt)}.`
                : null}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {citiesLoading || forecastLoading ? (
              <LoadingState label="Voorspelling wordt geladen..." />
            ) : forecastError ? (
              <Feedback
                title="Forecast niet geladen"
                description={forecastError}
                action={
                  <Button
                    variant="outline"
                    onClick={() => setForecastRetry((value) => value + 1)}
                  >
                    Opnieuw proberen
                  </Button>
                }
              />
            ) : forecasts.length === 0 ? (
              <Feedback
                title="Geen forecast-data"
                description="Er is nog geen succesvolle run voor deze stad."
              />
            ) : (
              <ChartContainer
                config={chartConfig}
                className="aspect-auto h-[340px] w-full cursor-pointer"
              >
                <AreaChart
                  accessibilityLayer
                  data={forecasts}
                  onClick={handleForecastClick}
                  onMouseMove={handleForecastHover}
                  margin={{ left: 8, right: 8, top: 8, bottom: 8 }}
                >
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="target_time"
                    tickLine={false}
                    axisLine={false}
                    minTickGap={28}
                    tickMargin={8}
                    tickFormatter={formatHourTick}
                  />
                  <YAxis
                    yAxisId="temp"
                    tickLine={false}
                    axisLine={false}
                    width={48}
                    tickFormatter={(value: number) => `${value}°`}
                  />
                  <YAxis
                    yAxisId="wind"
                    orientation="right"
                    tickLine={false}
                    axisLine={false}
                    width={48}
                    tickFormatter={(value: number) => `${value}`}
                  />
                  <ChartTooltip
                    content={
                      <ChartTooltipContent
                        labelFormatter={(value) =>
                          formatFullDateTime(String(value ?? ""))
                        }
                      />
                    }
                  />
                  <ChartLegend content={<ChartLegendContent />} />
                  {selectedTargetTime ? (
                    <ReferenceLine
                      x={selectedTargetTime}
                      yAxisId="temp"
                      stroke="currentColor"
                      strokeDasharray="4 4"
                      strokeOpacity={0.45}
                    />
                  ) : null}
                  <Area
                    yAxisId="temp"
                    type="monotone"
                    dataKey="temperature_2m"
                    stroke="var(--color-temperature_2m)"
                    fill="var(--color-temperature_2m)"
                    fillOpacity={0.15}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                  <Area
                    yAxisId="wind"
                    type="monotone"
                    dataKey="wind_speed_10m"
                    stroke="var(--color-wind_speed_10m)"
                    fill="var(--color-wind_speed_10m)"
                    fillOpacity={0.12}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                </AreaChart>
              </ChartContainer>
            )}
          </CardContent>
        </Card>

        {selectedTargetTime ? (
          <Card>
            <CardHeader className="border-b">
              <CardTitle>Revisie-geschiedenis</CardTitle>
              <CardDescription>
                Evolutie van de voorspelling voor{" "}
                {formatFullDateTime(selectedTargetTime)}
                {selectedCity ? ` in ${selectedCity.name}` : ""}. Elk punt is
                een opeenvolgende forecast-run.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {historyLoading ? (
                <LoadingState label="Revisiegeschiedenis wordt geladen..." />
              ) : historyError ? (
                <Feedback
                  title="Historie niet geladen"
                  description={historyError}
                  action={
                    <Button
                      variant="outline"
                      onClick={() => setHistoryRetry((value) => value + 1)}
                    >
                      Opnieuw proberen
                    </Button>
                  }
                />
              ) : history.length === 0 ? (
                <Feedback
                  title="Geen revisies"
                  description="Voor dit uur zijn geen succesvolle runs gevonden."
                />
              ) : (
                <div className="space-y-3">
                  {history.length === 1 ? (
                    <p className="text-sm text-muted-foreground">
                      Nog 1 run beschikbaar. Na meerdere ingesties wordt de
                      evolutie over opeenvolgende runs zichtbaar.
                    </p>
                  ) : null}
                  <ChartContainer
                    config={chartConfig}
                    className="aspect-auto h-[280px] w-full"
                  >
                    <LineChart
                      accessibilityLayer
                      data={history}
                      margin={{ left: 8, right: 8, top: 8, bottom: 8 }}
                    >
                      <CartesianGrid vertical={false} />
                      <XAxis
                        dataKey="forecast_run_at"
                        tickLine={false}
                        axisLine={false}
                        minTickGap={24}
                        tickMargin={8}
                        tickFormatter={formatRunTick}
                      />
                      <YAxis
                        yAxisId="temp"
                        tickLine={false}
                        axisLine={false}
                        width={48}
                        tickFormatter={(value: number) => `${value}°`}
                      />
                      <YAxis
                        yAxisId="wind"
                        orientation="right"
                        tickLine={false}
                        axisLine={false}
                        width={48}
                        tickFormatter={(value: number) => `${value}`}
                      />
                      <ChartTooltip
                        content={
                          <ChartTooltipContent
                            labelFormatter={(value) =>
                              formatFullDateTime(String(value ?? ""))
                            }
                          />
                        }
                      />
                      <ChartLegend content={<ChartLegendContent />} />
                      <Line
                        yAxisId="temp"
                        type="monotone"
                        dataKey="temperature_2m"
                        stroke="var(--color-temperature_2m)"
                        strokeWidth={2}
                        dot={{ r: 4 }}
                        activeDot={{ r: 6 }}
                      />
                      <Line
                        yAxisId="wind"
                        type="monotone"
                        dataKey="wind_speed_10m"
                        stroke="var(--color-wind_speed_10m)"
                        strokeWidth={2}
                        dot={{ r: 4 }}
                        activeDot={{ r: 6 }}
                      />
                    </LineChart>
                  </ChartContainer>
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}
      </main>
    </div>
  );
}
