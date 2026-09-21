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
      redirect: "error",
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
    if (response.status !== 200) throw new Error(`GitHub ${method} returned ${response.status}`);
    return response.json();
  };

  const actor = await api("/user");
  if (actor.login !== "NET86") throw new Error("GitHub credential must belong to NET86");
  const history = await api(WORKFLOW + "/runs?branch=main&per_page=1");
  if (!Array.isArray(history.workflow_runs)) throw new Error("Invalid workflow history");
  const latest = history.workflow_runs[0];
  if (latest) {
    const created = Date.parse(latest.created_at);
    if (latest.head_branch !== "main" || !Number.isFinite(created)) {
      throw new Error("Invalid latest workflow run");
    }
    // Let the existing workflow own validation, publication, recovery and failures.
    if (now - created < RECENT_MS) return { result: "skipped-recent-run", run_id: latest.id };
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
