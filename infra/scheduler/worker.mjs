const API = "https://api.github.com";
const WORKFLOW = "/repos/NET86/rules/actions/workflows/sync.yml";
const RECENT_MS = 5 * 60 * 60 * 1000;

// No storage or public endpoint: GitHub's run history is the only scheduling state.
/** @param {Env} env @param {typeof fetch} request @param {number} now */
export async function trigger(env, request = fetch, now = Date.now()) {
  if (!env.GITHUB_TOKEN) throw new Error("Missing GITHUB_TOKEN secret");
  /** @param {string} path @param {string} method @param {object} [body] */
  const api = async (path, method = "GET", body) => {
    const response = await request(API + path, {
      method,
      // Workers supports manual/follow, not redirect:error. Status checks reject 3xx.
      redirect: "manual",
      signal: AbortSignal.timeout(20_000),
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "NET86-rules-scheduler",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const expected = method === "PUT" ? 204 : 200;
    if (response.status !== expected) throw new Error(`GitHub ${method} returned ${response.status}`);
    return expected === 204 ? null : response.json();
  };

  const actor = await api("/user");
  if (actor.login !== "NET86") throw new Error("GitHub credential must belong to NET86");
  // A skipped GitHub backup is also a successful run. Never let it suppress the primary.
  const history = await api(WORKFLOW + "/runs?branch=main&event=workflow_dispatch&per_page=1");
  if (!Array.isArray(history.workflow_runs)) throw new Error("Invalid workflow history");
  const latest = history.workflow_runs[0];
  if (latest) {
    const created = Date.parse(latest.created_at);
    if (latest.head_branch !== "main" || !Number.isFinite(created)) {
      throw new Error("Invalid latest workflow run");
    }
    // Let the existing workflow own validation, publication, recovery and failures.
    if (now >= created && now - created < RECENT_MS) return { result: "skipped-recent-run", run_id: latest.id };
  }
  const workflow = await api(WORKFLOW);
  if (workflow.state === "disabled_manually") return { result: "skipped-disabled-workflow" };
  if (workflow.state === "disabled_inactivity") {
    await api(WORKFLOW + "/enable", "PUT");
  } else if (workflow.state !== "active") {
    throw new Error("Workflow is not active or disabled by inactivity");
  }
  // A no-op repository can also lose its independent weekly radar to inactivity.
  // Its recovery must not make the primary update depend on a secondary API call.
  try {
    const auditPath = "/repos/NET86/rules/actions/workflows/audit.yml";
    const audit = await api(auditPath);
    if (audit.state === "disabled_inactivity") {
      await api(auditPath + "/enable", "PUT");
    } else if (!["active", "disabled_manually"].includes(audit.state)) {
      throw new Error("Unexpected audit workflow state");
    }
  } catch (error) {
    console.warn("Secondary radar recovery failed:", String(error));
  }
  const dispatched = await api(WORKFLOW + "/dispatches", "POST", { ref: "main" });
  if (!Number.isSafeInteger(dispatched.workflow_run_id) || dispatched.workflow_run_id <= 0) {
    throw new Error("Invalid workflow dispatch response");
  }
  return { result: "dispatched", run_id: dispatched.workflow_run_id };
}

/** @satisfies {ExportedHandler<Env>} */
export default {
  async scheduled(_controller, env) {
    console.log(JSON.stringify(await trigger(env)));
  },
};
