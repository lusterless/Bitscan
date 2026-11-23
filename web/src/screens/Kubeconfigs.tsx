import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api/client";
import type { components } from "../api/schema";
import { toProblem, type ProblemInfo } from "../app/problems";
import { Confirm } from "../components/Confirm";
import { ProblemBanner } from "../components/ProblemBanner";
import { formatTime } from "../format";

type Kubeconfig = components["schemas"]["KubeconfigItem"];

/** TS §6.2: the manager refuses a kubeconfig over 1 MiB; checked here first. */
const MAX_BYTES = 1024 * 1024;
const UNAVAILABLE = "The manager is unavailable. Try again later.";

/** Reads a chosen file as text, or explains why not. */
async function readKubeconfig(file: File | null): Promise<string> {
  if (file === null) throw new Error("Choose a kubeconfig file.");
  if (file.size > MAX_BYTES) throw new Error("The file is larger than 1 MiB.");
  return file.text();
}

function Replace({
  item,
  onDone,
}: {
  item: Kubeconfig;
  onDone: (problem: ProblemInfo | null, note: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  if (!open) {
    return (
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => {
          setOpen(true);
        }}
      >
        Replace
      </button>
    );
  }
  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    try {
      const content = await readKubeconfig(file);
      const { data, error, response } = await api.PUT(
        "/api/v1/kubeconfigs/{kubeconfig_id}",
        {
          params: { path: { kubeconfig_id: item.kubeconfig_id } },
          body: { content },
        },
      );
      if (data !== undefined) {
        setOpen(false);
        onDone(null, "Kubeconfig " + item.name + " replaced.");
      } else onDone(toProblem(error, response), null);
    } catch (err) {
      onDone(null, err instanceof Error ? err.message : UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      aria-label={"Replace " + item.name}
      className="inline-field"
      onSubmit={(event) => void submit(event)}
    >
      <input
        type="file"
        aria-label="New kubeconfig file"
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
        }}
      />
      <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
        Upload
      </button>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => {
          setOpen(false);
        }}
      >
        Cancel
      </button>
    </form>
  );
}

/**
 * TS §3.8, §6.2 (owner decision 2026-11-23): the cluster-admin kubeconfigs
 * ClusterMAX scans may use. Admins only; changes need a TOTP-verified
 * session, so a refusal shows the sign-in-again prompt. The content is
 * sent once and never shown or returned.
 */
export function Kubeconfigs() {
  const [items, setItems] = useState<readonly Kubeconfig[] | null>(null);
  const [reload, setReload] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemInfo | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .GET("/api/v1/kubeconfigs", { params: { query: { limit: 500 } } })
      .then(({ data, error, response }) => {
        if (!active) return;
        if (data !== undefined) setItems(data.items);
        else setProblem(toProblem(error, response));
      })
      .catch(() => {
        if (active) setNote(UNAVAILABLE);
      });
    return () => {
      active = false;
    };
  }, [reload]);

  function done(p: ProblemInfo | null, n: string | null): void {
    setProblem(p);
    setNote(n);
    if (p === null && n !== null) setReload((r) => r + 1);
  }

  async function upload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setNote(null);
    setProblem(null);
    if (name.trim() === "") {
      setNote("Enter a name.");
      return;
    }
    setBusy(true);
    try {
      const content = await readKubeconfig(file);
      const { data, error, response } = await api.POST("/api/v1/kubeconfigs", {
        body: { name: name.trim(), description, content },
      });
      if (data !== undefined) {
        setName("");
        setDescription("");
        setFile(null);
        setFormKey((k) => k + 1); // clears the file input
        done(null, "Kubeconfig " + data.name + " uploaded.");
      } else setProblem(toProblem(error, response));
    } catch (err) {
      setNote(err instanceof Error ? err.message : UNAVAILABLE);
    } finally {
      setBusy(false);
    }
  }

  async function remove(item: Kubeconfig): Promise<void> {
    setNote(null);
    setProblem(null);
    try {
      const { error, response } = await api.DELETE(
        "/api/v1/kubeconfigs/{kubeconfig_id}",
        { params: { path: { kubeconfig_id: item.kubeconfig_id } } },
      );
      if (response.ok) done(null, "Kubeconfig " + item.name + " deleted.");
      else setProblem(toProblem(error, response));
    } catch {
      setNote(UNAVAILABLE);
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <div>
          <h1>Kubeconfigs</h1>
        </div>
      </div>
      {note !== null && (
        <p role="status" className="callout callout-warning">
          {note}
        </p>
      )}
      <ProblemBanner problem={problem} />
      <form
        key={formKey}
        aria-label="Upload kubeconfig"
        className="card form form-wide"
        onSubmit={(event) => void upload(event)}
      >
        <h2>Upload</h2>
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
          Description
          <input
            value={description}
            maxLength={1000}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        </label>
        <label>
          File
          <input
            type="file"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
            }}
          />
        </label>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Upload
          </button>
        </div>
      </form>
      <section className="card card-flush" aria-labelledby="kubeconfigs-title">
        <h2 id="kubeconfigs-title" className="card-title">
          Kubeconfigs
        </h2>
        {items === null ? (
          <p className="muted">Loading.</p>
        ) : items.length === 0 ? (
          <p className="empty">No kubeconfig uploaded.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Cluster</th>
                  <th>Server</th>
                  <th>Description</th>
                  <th>Uploaded</th>
                  <th>Replaced</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.kubeconfig_id}>
                    <td>{item.name}</td>
                    <td>{item.cluster_name}</td>
                    <td className="mono">{item.server}</td>
                    <td>{item.description}</td>
                    <td>{formatTime(item.created_at)}</td>
                    <td>
                      {item.replaced_at === null
                        ? "never"
                        : formatTime(item.replaced_at)}
                    </td>
                    <td>
                      {item.deleted_at !== null ? (
                        "deleted " + formatTime(item.deleted_at)
                      ) : (
                        <div className="form-actions">
                          <Replace item={item} onDone={done} />
                          <Confirm
                            tone="danger"
                            label="Delete"
                            message={
                              "Delete " +
                              item.name +
                              "? Its content is erased; old scans keep the name."
                            }
                            onConfirm={() => {
                              void remove(item);
                            }}
                          />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
