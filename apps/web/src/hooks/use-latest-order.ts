"use client";

import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";

import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import { changesOrders, getLatestOrder, type Order } from "@/lib/orders";

export type LatestOrderState = {
  /** The latest order; null when there is none yet, undefined while it loads. */
  order: Order | null | undefined;
  /** Why it could not be loaded, if it could not. */
  error: string | null;
};

const LatestOrderContext = createContext<LatestOrderState | null>(null);

/**
 * The latest order for the /demo page's panels that follow it (Payments, the makers' phones), loaded once for all of
 * them, and again whenever the event stream says it may have changed: an order or a share moved, a maker was told,
 * or her proof of shipping moved on. Put it inside the EventStreamProvider.
 */
export function LatestOrderProvider({ children }: { children: ReactNode }) {
  const { events } = useEventStream();
  // Events are newest first: the newest one about an order, a share, a notice or a tracking.
  const lastChange = events.find(changesOrders)?.id ?? 0;
  const [state, setState] = useState<LatestOrderState>({ order: undefined, error: null });

  useEffect(() => {
    const controller = new AbortController();
    getLatestOrder({ signal: controller.signal })
      .then((order) => setState({ order, error: null }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, error: errorMessage(reason) }));
      });
    return () => controller.abort();
  }, [lastChange]);

  return createElement(LatestOrderContext.Provider, { value: state }, children);
}

/** The latest order, from the LatestOrderProvider around the page. */
export function useLatestOrder(): LatestOrderState {
  const state = useContext(LatestOrderContext);
  if (state === null) throw new Error("useLatestOrder needs a LatestOrderProvider around it");
  return state;
}
