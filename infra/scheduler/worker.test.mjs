import assert from "node:assert/strict";
import test from "node:test";
import worker, { trigger } from "./worker.mjs";

const now = Date.parse("2026-09-21T06:49:00Z");
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
});

test("stale or absent history dispatches only the fixed main workflow", async () => {
  for (const history of [[], [run(6)]]) {
    const { request, calls } = mock({ login: "NET86" }, { workflow_runs: history }, { workflow_run_id: 8 });
    assert.deepEqual(await trigger(secret, request, now), { result: "dispatched", run_id: 8 });
    assert.equal(calls[2].url, "https://api.github.com/repos/NET86/rules/actions/workflows/sync.yml/dispatches");
    assert.deepEqual(JSON.parse(calls[2].options.body), { ref: "main" });
    assert.equal(calls[2].options.method, "POST");
    for (const { options } of calls) {
      assert.equal(options.redirect, "error");
      assert.ok(options.signal instanceof AbortSignal);
    }
  }
});

test("API and malformed-response failures stay visible and never retry dispatch", async () => {
  const scenarios = [
    [401],
    [{ login: "NET86" }, {}],
    [{ login: "NET86" }, { workflow_runs: [{ ...run(6), head_branch: "other" }] }],
    [{ login: "NET86" }, { workflow_runs: [] }, 403],
    [{ login: "NET86" }, { workflow_runs: [] }, { workflow_run_id: null }],
  ];
  for (const responses of scenarios) {
    const { request, calls } = mock(...responses);
    await assert.rejects(trigger(secret, request, now));
    assert.ok(calls.filter(({ options }) => options.method === "POST").length <= 1);
  }
});
