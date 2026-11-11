import { api } from "../api/client";
import type { operations } from "../api/schema";
import { toProblem, type ProblemInfo } from "./problems";

export type CsvQuery = NonNullable<
  operations["search_packages_csv_api_v1_packages_search_csv_get"]["parameters"]["query"]
>;

export type ResultsCsvQuery = NonNullable<
  operations["results_csv_api_v1_scans__id__results_csv_get"]["parameters"]["query"]
>;

/** The name the manager gives in its Content-Disposition (#84 (c)). */
export const CSV_FILE_NAME = "packages.csv";

/**
 * The name the manager gives a scan's results export in its
 * Content-Disposition (#146 (d)): the canonical lower-case scan id.
 */
export function resultsCsvFileName(scanId: string): string {
  return "scan-" + scanId.toLowerCase() + "-results.csv";
}

/** Saves a Blob as a file through a temporary object URL, revoked afterwards. */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked on the next task: some browsers read the URL just after click().
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

/** What the generated client answers for a `parseAs: "blob"` request. */
interface BlobAnswer {
  readonly data?: Blob;
  readonly error?: unknown;
  readonly response: Response;
}

/**
 * Saves a CSV the generated client fetched with `parseAs: "blob"`, or
 * returns the refusal's problem and saves nothing. The body is saved
 * unchanged: the server has already escaped formula cells (TS §6.3).
 */
async function saveCsv(
  request: Promise<BlobAnswer>,
  fileName: string,
): Promise<ProblemInfo | null> {
  const { data, error, response } = await request;
  if (data === undefined) {
    return toProblem(error, response);
  }
  saveBlob(data, fileName);
  return null;
}

/**
 * REQ-131: the export goes through the generated client, so the bearer header
 * is sent (a plain link could not carry it).
 */
export async function downloadCsv(
  query: CsvQuery,
): Promise<ProblemInfo | null> {
  return saveCsv(
    api.GET("/api/v1/packages/search.csv", {
      params: { query },
      parseAs: "blob",
    }),
    CSV_FILE_NAME,
  );
}

/**
 * REQ-281 (3): a scan's results export with the screen's current filters
 * (`status`, `agent_id`; no cursor, the whole set), through the generated
 * client as above.
 */
export async function downloadResultsCsv(
  scanId: string,
  query: ResultsCsvQuery,
): Promise<ProblemInfo | null> {
  return saveCsv(
    api.GET("/api/v1/scans/{id}/results.csv", {
      params: { path: { id: scanId }, query },
      parseAs: "blob",
    }),
    resultsCsvFileName(scanId),
  );
}
