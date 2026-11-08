import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { ProblemBanner } from "../components/ProblemBanner";
import {
  ALL_HOSTS,
  TargetPicker,
  fromTarget,
  toTarget,
  type TargetValue,
} from "../components/TargetPicker";

type Schedule = components["schemas"]["ScheduleItem"];
type Policy = components["schemas"]["PolicyItem"];
type Change = components["schemas"]["PatchSchedule"];

export interface ScheduleFormProps {
  /** The schedule to edit, or null to create one. */
  readonly schedule: Schedule | null;
  /** The profiles a new schedule may use (enabled or disabled, #122 (h)). */
  readonly policies: readonly Policy[];
  readonly onSaved: () => void;
  readonly onCancel: () => void;
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * REQ-282 (1): create sends the #122 (h) body; an edit sends only the
 * changed fields (the profile cannot change: make a new schedule).
 */
export function ScheduleForm({
  schedule,
  policies,
  onSaved,
  onCancel,
}: ScheduleFormProps) {
  const [name, setName] = useState(schedule?.name ?? "");
  const [policyId, setPolicyId] = useState(
    schedule === null ? "" : String(schedule.policy_id),
  );
  const [target, setTarget] = useState<TargetValue>(
    schedule === null ? ALL_HOSTS : fromTarget(schedule.target),
  );
  const [cron, setCron] = useState(schedule?.cron ?? "");
  const [timezone, setTimezone] = useState(schedule?.timezone ?? "UTC");
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setProblem(null);
    const body = toTarget(target);
    if (typeof body === "string") {
      setNote(body);
      return;
    }
    let send: () => Promise<{ error?: unknown; response: Response }>;
    if (schedule === null) {
      if (policyId === "") {
        setNote("Choose a profile.");
        return;
      }
      const create = {
        name,
        policy_id: Number(policyId),
        target: body,
        cron,
        timezone,
        enabled,
      };
      send = () => api.POST("/api/v1/scan-schedules", { body: create });
    } else {
      const change: Change = {};
      if (name !== schedule.name) change.name = name;
      if (!same(body, schedule.target)) change.target = body;
      if (cron !== schedule.cron) change.cron = cron;
      if (timezone !== schedule.timezone) change.timezone = timezone;
      if (enabled !== schedule.enabled) change.enabled = enabled;
      if (Object.keys(change).length === 0) {
        setNote("Nothing has changed.");
        return;
      }
      const id = String(schedule.schedule_id);
      send = () =>
        api.PATCH("/api/v1/scan-schedules/{id}", {
          params: { path: { id } },
          body: change,
        });
    }
    setNote(null);
    setBusy(true);
    try {
      const { error, response } = await send();
      if (response.ok) onSaved();
      else setProblem(toProblem(error, response));
    } catch {
      setNote("The manager is unavailable. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      aria-label={schedule === null ? "New schedule" : "Edit schedule"}
      className="card form form-wide"
      onSubmit={(event) => void save(event)}
    >
      <h2>{schedule === null ? "New schedule" : "Edit " + schedule.name}</h2>
      {note !== null && (
        <p role="alert" className="callout callout-danger">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <label>
        Name
        <input
          value={name}
          maxLength={128}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </label>
      <label>
        Profile
        <select
          value={policyId}
          disabled={schedule !== null}
          onChange={(event) => {
            setPolicyId(event.target.value);
          }}
        >
          <option value="">Choose a profile</option>
          {policies.map((policy) => (
            <option key={policy.policy_id} value={String(policy.policy_id)}>
              {policy.policy_name}
            </option>
          ))}
        </select>
      </label>
      <TargetPicker value={target} onChange={setTarget} />
      <label>
        Cron (minute hour day-of-month month day-of-week)
        <input
          value={cron}
          maxLength={64}
          onChange={(event) => {
            setCron(event.target.value);
          }}
        />
      </label>
      <label>
        Time zone (IANA name)
        <input
          value={timezone}
          maxLength={64}
          onChange={(event) => {
            setTimezone(event.target.value);
          }}
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => {
            setEnabled(event.target.checked);
          }}
        />
        Enabled
      </label>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          Save
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
