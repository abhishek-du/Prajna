import { lazy } from "react";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router";
import { AppShell } from "./components/shell/AppShell";

/* Route-level code splitting: each screen is its own chunk. */
const Overview = lazy(() => import("./routes/Overview"));
const Markets = lazy(() => import("./routes/Markets"));
const Stocks = lazy(() => import("./routes/Stocks"));
const StockDetail = lazy(() => import("./routes/StockDetail"));
const Sectors = lazy(() => import("./routes/Sectors"));
const SectorDetail = lazy(() => import("./routes/SectorDetail"));
const Global = lazy(() => import("./routes/Global"));
const News = lazy(() => import("./routes/News"));
const Watchlist = lazy(() => import("./routes/Watchlist"));
const DataQuality = lazy(() => import("./routes/DataQuality"));
const Operations = lazy(() => import("./routes/Operations"));
const Acceptance = lazy(() => import("./routes/Acceptance"));
const NotFound = lazy(() => import("./routes/NotFound"));

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <Overview /> },
      { path: "markets", element: <Markets /> },
      { path: "stocks", element: <Stocks /> },
      { path: "stocks/:key", element: <StockDetail /> },
      { path: "sectors", element: <Sectors /> },
      { path: "sectors/:sector", element: <SectorDetail /> },
      { path: "global", element: <Global /> },
      { path: "news", element: <News /> },
      { path: "watchlist", element: <Watchlist /> },
      { path: "data-quality", element: <DataQuality /> },
      { path: "operations", element: <Operations /> },
      { path: "operations/acceptance", element: <Acceptance /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
