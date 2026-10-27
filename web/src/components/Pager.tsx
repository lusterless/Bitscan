import { useCallback, useMemo, useState } from "react";

/**
 * Cursor paging state for one list (TS §6.3: `?limit=&cursor=`). The API only
 * returns `next_cursor`, so going back re-requests the cursor of the page
 * before, kept here; `cursor` is null on the first page.
 */
export interface CursorPages {
  readonly cursor: string | null;
  readonly hasPrevious: boolean;
  /** 1 on the first page; absent when the caller does not track it. */
  readonly page?: number;
  readonly next: (cursor: string) => void;
  readonly previous: () => void;
  readonly reset: () => void;
}

export function useCursorPages(): CursorPages {
  // The cursors of every page after the first, in the order they were opened.
  const [stack, setStack] = useState<readonly string[]>([]);
  const next = useCallback((cursor: string) => {
    setStack((pages) => [...pages, cursor]);
  }, []);
  const previous = useCallback(() => {
    setStack((pages) => pages.slice(0, -1));
  }, []);
  const reset = useCallback(() => {
    setStack([]);
  }, []);
  return useMemo(
    () => ({
      cursor: stack.length === 0 ? null : (stack[stack.length - 1] ?? null),
      hasPrevious: stack.length > 0,
      page: stack.length + 1,
      next,
      previous,
      reset,
    }),
    [stack, next, previous, reset],
  );
}

export interface PagerProps {
  readonly pages: CursorPages;
  /** `next_cursor` of the page on screen; null on the last page. */
  readonly nextCursor: string | null;
  readonly disabled?: boolean;
}

export function Pager({ pages, nextCursor, disabled = false }: PagerProps) {
  return (
    <nav aria-label="Pages" className="pager">
      {pages.page !== undefined && (
        <span className="pager-info">Page {pages.page}</span>
      )}
      <button
        type="button"
        className="btn btn-sm"
        disabled={disabled || !pages.hasPrevious}
        onClick={pages.previous}
      >
        Previous
      </button>
      <button
        type="button"
        className="btn btn-sm"
        disabled={disabled || nextCursor === null}
        onClick={() => {
          if (nextCursor !== null) {
            pages.next(nextCursor);
          }
        }}
      >
        Next
      </button>
    </nav>
  );
}
