import assert from "node:assert/strict";
import test from "node:test";
import worker, { trigger } from "./worker.mjs";

const now = Date.parse("2026-09-21T04:01:00Z");
const secret = { GITHUB_TOKEN: "test-only-secret" };
const run = (hours) => ({ id: 7, head_branch: "main", created_at: new Date(now - hours * 3600000).toISOString() });
function mock(...responses) {
  const calls = [];
  const request = async (url, options) => {
    calls.push({ url, options });
    assert.ok(responses.length, "unexpected extra API request");
    const value = responses.shift();
    if (typeof value === "number") return new Response(null, { status: value });
    return Response.json(value);
  };
  return { request, calls };
}

test("no public HTTP handler; scheduled work is awaited", async () => {
  assert.equal(worker.fetch, undefined);
  await assert.rejects(worker.scheduled({}, {}), /Missing GITHUB_TOKEN/);
});

test("identity mismatch cannot read or dispatch repository workflows", async () => {
  const { request, calls } = mock({ login: "unrelated-user" });
  await assert.rejects(trigger(secret, request, now), /must belong to NET86/);
  assert.equal(calls.length, 1);
});

test("a recent GitHub run avoids a duplicate build", async () => {
  const { request, calls } = mock({ login: "NET86" }, { workflow_runs: [run(1)] });
  assert.equal((await trigger(secret, request, now)).result, "skipped-recent-run");
  assert.equal(calls.length, 2);
  assert.equal(new URL(calls[1].url).searchParams.get("event"), "workflow_dispatch");
});

test("stale or absent history dispatches only the fixed main workflow", async () => {
  for (const history of [[], [run(6)], [run(-1)]]) {
    const { request, calls } = mock({ login: "NET86" }, { workflow_runs: history }, { state: "active" }, { state: "active" }, { workflow_run_id: 8 });
    assert.deepEqual(await trigger(secret, request, now), { result: "dispatched", run_id: 8 });
    assert.equal(calls[4].url, "https://api.github.com/repos/NET86/rules/actions/workflows/sync.yml/dispatches");
    assert.deepEqual(JSON.parse(calls[4].options.body), { ref: "main" });
    assert.equal(calls[4].options.method, "POST");
    for (const { options } of calls) {
      assert.equal(options.redirect, "manual");
      assert.ok(options.signal instanceof AbortSignal);
    }
  }
});

test("GitHub inactivity disabling is recovered before dispatch", async () => {
  const { request, calls } = mock({ login: "NET86" }, { workflow_runs: [run(60 * 24)] },
                                { state: "disabled_inactivity" }, 204, { state: "active" }, { workflow_run_id: 8 });
  assert.equal((await trigger(secret, request, now)).result, "dispatched");
  assert.equal(calls[3].url, "https://api.github.com/repos/NET86/rules/actions/workflows/sync.yml/enable");
  assert.equal(calls[3].options.method, "PUT");
  assert.equal(calls[5].options.method, "POST");
});

test("an owner's manual disable is respected", async () => {
  const { request, calls } = mock({ login: "NET86" }, { workflow_runs: [] }, { state: "disabled_manually" });
  assert.equal((await trigger(secret, request, now)).result, "skipped-disabled-workflow");
  assert.ok(calls.every(({ options }) => options.method === "GET"));
});

test("API and malformed-response failures stay visible and never retry dispatch", async () => {
  const scenarios = [
    [401],
    [302],
    [{ login: "NET86" }, { workflow_runs: [] }, { state: "active" }, { state: "active" }, 307],
    [{ login: "NET86" }, {}],
    [{ login: "NET86" }, { workflow_runs: [{ ...run(6), head_branch: "other" }] }],
    [{ login: "NET86" }, { workflow_runs: [] }, { state: "active" }, { state: "active" }, 403],
    [{ login: "NET86" }, { workflow_runs: [] }, { state: "active" }, { state: "active" }, { workflow_run_id: null }],
    [{ login: "NET86" }, { workflow_runs: [] }, { state: "disabled_inactivity" }, 403],
    [{ login: "NET86" }, { workflow_runs: [] }, { state: "unknown" }],
  ];
  for (const responses of scenarios) {
    const { request, calls } = mock(...responses);
    await assert.rejects(trigger(secret, request, now));
    assert.ok(calls.filter(({ options }) => options.method === "POST").length <= 1);
  }
});

test("secondary inactivity is repaired but manual disable and failures never block primary", async () => {
  for (const responses of [[{ state: "disabled_inactivity" }, 204], [{ state: "disabled_manually" }],
                           [503], [{ state: "disabled_inactivity" }, 403], [{ state: "unknown" }]]) {
    const { request, calls } = mock({ login: "NET86" }, { workflow_runs: [] }, { state: "active" },
                                  ...responses, { workflow_run_id: 8 });
    assert.deepEqual(await trigger(secret, request, now), { result: "dispatched", run_id: 8 });
    assert.equal(calls[3].url, "https://api.github.com/repos/NET86/rules/actions/workflows/audit.yml");
    const writes = calls.filter(({ options }) => options.method !== "GET");
    assert.equal(writes.filter(({ options }) => options.method === "POST").length, 1);
    if (responses[0].state === "disabled_inactivity") {
      assert.equal(writes[0].url, "https://api.github.com/repos/NET86/rules/actions/workflows/audit.yml/enable");
    } else {
      assert.equal(writes.length, 1);
    }
  }
});
