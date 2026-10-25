import { api } from "../api/client";
import type { operations } from "../api/schema";
import { toProblem, type ProblemInfo } from "./problems";

export type CsvQuery = NonNullable<
  operations["search_packages_csv_api_v1_packages_search_csv_get"]["parameters"]["query"]
>;

/** The name the manager gives in its Content-Disposition (#84 (c)). */
export const CSV_FILE_NAME = "packages.csv";

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

/**
 * REQ-131: the export goes through the generated client, so the bearer header
 * is sent (a plain link could not carry it). The body is saved unchanged; the
 * server has already escaped formula cells (TS §6.3).
 */
export async function downloadCsv(
  query: CsvQuery,
): Promise<ProblemInfo | null> {
  const { data, error, response } = await api.GET(
    "/api/v1/packages/search.csv",
    { params: { query }, parseAs: "blob" },
  );
  if (data === undefined) {
    return toProblem(error, response);
  }
  saveBlob(data, CSV_FILE_NAME);
  return null;
}
