import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { MarketDataProviderRoot } from "./providers/marketData";
import { SettingsProvider } from "./providers/settings";
import { routes } from "./router";

export function renderRoute(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <SettingsProvider>
      <QueryClientProvider client={client}>
        <MarketDataProviderRoot>
          <RouterProvider router={router} />
        </MarketDataProviderRoot>
      </QueryClientProvider>
    </SettingsProvider>,
  );
  return { ...utils, router, client };
}
