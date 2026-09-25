import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { ApiError } from "./api/http";
import { MarketDataProviderRoot } from "./providers/marketData";
import { SettingsProvider } from "./providers/settings";
import { router } from "./router";
import "./styles/tokens.css";
import "./styles/app.css";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // do not hammer the API: a 4xx is final, other failures retry twice
        retry: (n, e) => !(e instanceof ApiError && e.status !== null && e.status < 500) && n < 2,
      },
    },
  });
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <SettingsProvider>
        <QueryClientProvider client={makeQueryClient()}>
          <MarketDataProviderRoot>
            <RouterProvider router={router} />
          </MarketDataProviderRoot>
        </QueryClientProvider>
      </SettingsProvider>
    </StrictMode>,
  );
}
