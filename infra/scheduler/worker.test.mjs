import assert from "node:assert/strict";
import test from "node:test";
import worker, { trigger } from "./worker.mjs";

const secret = { GITHUB_TOKEN: "[REDACTED_SECRET]" };
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
  await assert.rejects(trigger(secret, request), /must belong to NET86/);
  assert.equal(calls.length, 1);
});

test("every cron invocation dispatches the fixed main workflow without run-history deduplication", async () => {
  for (let i = 0; i < 2; i += 1) {
    const { request, calls } = mock(
      { login: "NET86" }, { state: "active" }, { state: "active" }, { workflow_run_id: 8 + i }
    );
    assert.deepEqual(await trigger(secret, request), { result: "dispatched", run_id: 8 + i });
    assert.equal(calls.length, 4);
    assert.ok(calls.every(({ url }) => !url.includes("/runs?")));
    assert.equal(calls[3].url, "https://api.github.com/repos/NET86/rules/actions/workflows/sync.yml/dispatches");
    assert.deepEqual(JSON.parse(calls[3].options.body), { ref: "main" });
    assert.equal(calls[3].options.method, "POST");
    for (const { options } of calls) {
      assert.equal(options.redirect, "manual");
      assert.ok(options.signal instanceof AbortSignal);
    }
  }
});

test("GitHub inactivity disabling is recovered before dispatch", async () => {
  const { request, calls } = mock(
    { login: "NET86" }, { state: "disabled_inactivity" }, 204, { state: "active" }, { workflow_run_id: 8 }
  );
  assert.equal((await trigger(secret, request)).result, "dispatched");
  assert.equal(calls[2].url, "https://api.github.com/repos/NET86/rules/actions/workflows/sync.yml/enable");
  assert.equal(calls[2].options.method, "PUT");
  assert.equal(calls[4].options.method, "POST");
});

test("an owner's manual disable is respected", async () => {
  const { request, calls } = mock({ login: "NET86" }, { state: "disabled_manually" });
  assert.equal((await trigger(secret, request)).result, "skipped-disabled-workflow");
  assert.ok(calls.every(({ options }) => options.method === "GET"));
});

test("API and malformed-response failures stay visible and never retry dispatch", async () => {
  const scenarios = [
    [401],
    [302],
    [{ login: "NET86" }, {}],
    [{ login: "NET86" }, { state: "active" }, { state: "active" }, 307],
    [{ login: "NET86" }, { state: "active" }, { state: "active" }, 403],
    [{ login: "NET86" }, { state: "active" }, { state: "active" }, { workflow_run_id: null }],
    [{ login: "NET86" }, { state: "disabled_inactivity" }, 403],
    [{ login: "NET86" }, { state: "unknown" }],
  ];
  for (const responses of scenarios) {
    const { request, calls } = mock(...responses);
    await assert.rejects(trigger(secret, request));
    assert.ok(calls.filter(({ options }) => options.method === "POST").length <= 1);
  }
});

test("secondary inactivity is repaired but manual disable and failures never block primary", async () => {
  for (const responses of [[{ state: "disabled_inactivity" }, 204], [{ state: "disabled_manually" }],
                           [503], [{ state: "disabled_inactivity" }, 403], [{ state: "unknown" }]]) {
    const { request, calls } = mock({ login: "NET86" }, { state: "active" }, ...responses, { workflow_run_id: 8 });
    assert.deepEqual(await trigger(secret, request), { result: "dispatched", run_id: 8 });
    assert.equal(calls[2].url, "https://api.github.com/repos/NET86/rules/actions/workflows/audit.yml");
    const writes = calls.filter(({ options }) => options.method !== "GET");
    assert.equal(writes.filter(({ options }) => options.method === "POST").length, 1);
    if (responses[0].state === "disabled_inactivity") {
      assert.equal(writes[0].url, "https://api.github.com/repos/NET86/rules/actions/workflows/audit.yml/enable");
    } else {
      assert.equal(writes.length, 1);
    }
  }
});
