// TS §3.8, §6.2 (owner decision 2026-11-23): the admin kubeconfig page. The
// content is sent once on upload or replace and never shown; a deleted entry
// keeps its name; every stored value renders as text.
import {
  answer,
  bsu,
  callsTo,
  json,
  loginResponse,
  noContent,
  problem,
  resetHttp,
} from "../test/harness";
import { IMG, SCRIPT, at, noInjectedMarkup, settle } from "../test/m11";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearSession, setSession } from "../app/session";
import { Kubeconfigs } from "./Kubeconfigs";

const LIST = "/api/v1/kubeconfigs";
const CONTENT = "apiVersion: v1\nkind: Config\n";

function item(id: number, extra: Record<string, unknown> = {}) {
  return {
    kubeconfig_id: id,
    name: "cluster-" + String(id),
    description: "d",
    cluster_name: "c" + String(id),
    server: "https://k" + String(id) + ":6443",
    created_at: "2026-11-23T00:00:00Z",
    created_by: 1,
    replaced_at: null,
    deleted_at: null,
    ...extra,
  };
}

function server(items: unknown[], write = () => json(201, item(9))): void {
  answer((call) => {
    if (call.path === LIST && call.method === "GET")
      return json(200, { items, next_cursor: null });
    return write();
  });
}

function chooseFile(input: HTMLElement, text: string): void {
  const file = new File([text], "kubeconfig.yaml", { type: "text/yaml" });
  fireEvent.change(input, { target: { files: [file] } });
}

async function mount() {
  const view = render(<Kubeconfigs />);
  await settle();
  return view;
}

beforeEach(() => {
  resetHttp();
  setSession(loginResponse("admin", true, bsu("A")));
});
afterEach(() => {
  clearSession();
});

describe("Kubeconfigs", () => {
  it("lists every kubeconfig as text, a deleted one without actions", async () => {
    server([
      item(1, { name: SCRIPT, description: IMG }),
      item(2, { deleted_at: "2026-11-23T02:00:00Z" }),
    ]);
    const view = await mount();
    expect(view.container.textContent).toContain(SCRIPT);
    expect(noInjectedMarkup(view.container)).toEqual({ scripts: 0, imgs: 0 });
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(
      within(at(rows, 1)).getByRole("button", { name: "Delete" }),
    ).toBeTruthy();
    expect(within(at(rows, 2)).queryByRole("button")).toBeNull();
    expect(at(rows, 2).textContent).toContain("deleted");
  });

  it("uploads name, description and the file's content", async () => {
    server([]);
    await mount();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: " prod " },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "GPU cluster" },
    });
    chooseFile(screen.getByLabelText("File"), CONTENT);
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await settle();
    const posts = callsTo(LIST, "POST");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(at(posts, 0).body)).toEqual({
      name: "prod",
      description: "GPU cluster",
      content: CONTENT,
    });
    expect(screen.getByRole("status").textContent).toBe(
      "Kubeconfig cluster-9 uploaded.",
    );
    expect(callsTo(LIST)).toHaveLength(2); // reloaded
    expect(document.body.textContent).not.toContain("kind: Config");
  });

  it("refuses a file over 1 MiB without sending it", async () => {
    server([]);
    await mount();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    chooseFile(screen.getByLabelText("File"), "a".repeat(1024 * 1024 + 1));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await settle();
    expect(callsTo(LIST, "POST")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe(
      "The file is larger than 1 MiB.",
    );
  });

  it("shows the server's refusal", async () => {
    server([], () =>
      problem(422, "invalid_request", "Invalid request: a user with exec"),
    );
    await mount();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    chooseFile(screen.getByLabelText("File"), CONTENT);
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await settle();
    expect(document.body.textContent).toContain(
      "Invalid request: a user with exec",
    );
  });

  it("replaces a kubeconfig's content", async () => {
    server([item(1)], () => json(200, item(1)));
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    chooseFile(screen.getByLabelText("New kubeconfig file"), CONTENT);
    const form = screen.getByRole("form", { name: "Replace cluster-1" });
    fireEvent.click(within(form).getByRole("button", { name: "Upload" }));
    await settle();
    const puts = callsTo(LIST + "/1", "PUT");
    expect(puts).toHaveLength(1);
    expect(JSON.parse(at(puts, 0).body)).toEqual({ content: CONTENT });
  });

  it("deletes after a confirmation", async () => {
    server([item(1)], noContent);
    await mount();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(callsTo(LIST + "/1", "DELETE")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await settle();
    expect(callsTo(LIST + "/1", "DELETE")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe(
      "Kubeconfig cluster-1 deleted.",
    );
  });
});
