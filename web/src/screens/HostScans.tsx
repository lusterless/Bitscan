import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Pager, useCursorPages } from "../components/Pager";
import { ProblemBanner } from "../components/ProblemBanner";
import { ScanTable, type ScanLinks } from "../components/ScanTable";

type Page = components["schemas"]["Page_ScanItem_"];

export interface HostScansProps {
  readonly agentId: string;
  readonly links: ScanLinks;
}

const PAGE_SIZE = 20;

/**
 * REQ-283: the host's scan history (`GET /agents/{id}/scans`), paged, each
 * row linking to its scan detail. Mount it with `key={agentId}`.
 */
export function HostScans({ agentId, links }: HostScansProps) {
  const pages = useCursorPages();
  const [page, setPage] = useState<Page | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    const cursor = pages.cursor === null ? {} : { cursor: pages.cursor };
    api
      .GET("/api/v1/agents/{id}/scans", {
        params: {
          path: { id: agentId },
          query: { limit: PAGE_SIZE, ...cursor },
        },
      })
      .then(({ data, error, response }) => {
        if (!active) return;
        setUnreachable(false);
        setPage(data ?? null);
        setProblem(data === undefined ? toProblem(error, response) : null);
      })
      .catch(() => {
        if (active) setUnreachable(true);
      });
    return () => {
      active = false;
    };
  }, [agentId, pages.cursor]);

  return (
    <section className="card card-flush" aria-labelledby="host-scans">
      <h2 id="host-scans" className="card-title">
        Scans
      </h2>
      {unreachable && (
        <p role="alert" className="callout callout-danger">
          The manager is unavailable. Try again later.
        </p>
      )}
      <ProblemBanner problem={problem} />
      {page !== null && page.items.length === 0 && (
        <p className="empty">No scans of this host yet.</p>
      )}
      {page !== null && page.items.length > 0 && (
        <ScanTable items={page.items} links={links} />
      )}
      <div className="card-foot">
        <Pager pages={pages} nextCursor={page?.next_cursor ?? null} />
      </div>
    </section>
  );
}
