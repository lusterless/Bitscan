import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";

export interface TypeAheadProps {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  /** A suggested name was chosen. */
  readonly onChoose: (name: string) => void;
}

const MIN_CHARS = 3;
const DELAY_MS = 300;
const LIMIT = 500;
const SHOWN = 10;

/** The first distinct names, in response (name) order. */
function firstNames(items: readonly object[]): string[] {
  const names: string[] = [];
  for (const item of items) {
    if (!("name" in item) || typeof item.name !== "string") continue;
    if (!names.includes(item.name)) names.push(item.name);
    if (names.length === SHOWN) break;
  }
  return names;
}

/**
 * REQ-130 per #32: from 3 characters and 300 ms without typing, one
 * `group_by=package` search with `limit=500`; at most 10 names are offered.
 * An answer for an older input is ignored.
 */
export function TypeAhead({
  label,
  value,
  onChange,
  onChoose,
}: TypeAheadProps) {
  const [names, setNames] = useState<readonly string[]>([]);
  const latest = useRef(0);

  useEffect(() => {
    latest.current += 1;
    const ticket = latest.current;
    if (Array.from(value).length < MIN_CHARS) {
      setNames([]);
      return;
    }
    const timer = setTimeout(() => {
      api
        .GET("/api/v1/packages/search", {
          params: { query: { q: value, group_by: "package", limit: LIMIT } },
        })
        .then(({ data }) => {
          if (ticket === latest.current) {
            setNames(data === undefined ? [] : firstNames(data.items));
          }
        })
        .catch(() => {
          if (ticket === latest.current) setNames([]);
        });
    }, DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [value]);

  return (
    <div>
      <label>
        {label}
        <input
          value={value}
          autoComplete="off"
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      </label>
      {names.length > 0 && (
        <ul aria-label="Suggestions">
          {names.map((name) => (
            <li key={name}>
              <button
                type="button"
                onClick={() => {
                  setNames([]);
                  onChoose(name);
                }}
              >
                {name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
