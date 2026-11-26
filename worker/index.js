// Cloudflare Worker (Cron Trigger every 30 min) -> starts the GitHub "watchdog" workflow only around the
// posting slots, so GitHub Actions never runs a blind 30-minute cron. Slots are in America/New_York
// (Intl handles DST). Secret: GH_TOKEN (fine-grained PAT, Actions: read/write on stoic-automation ONLY).
const REPO = "obelixagency/stoic-automation";
const WORKFLOW = "watchdog.yml";
const SLOTS_ET_MIN = [7 * 60 + 30, 12 * 60 + 30, 20 * 60 + 30];   // morning, midday, evening
const BEFORE_MIN = 60;    // start an hour early so the plan/render are ready before the slot
const AFTER_MIN = 210;    // keep retrying until past the 2.5h escalation window

function etMinutes(date) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(date);
  const h = Number(parts.find(p => p.type === "hour").value) % 24;
  const m = Number(parts.find(p => p.type === "minute").value);
  return h * 60 + m;
}

export function shouldDispatch(date) {
  const now = etMinutes(date);
  return SLOTS_ET_MIN.some(s => now >= s - BEFORE_MIN && now <= s + AFTER_MIN);
}

async function dispatch(env) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "unshaken-trigger", "X-GitHub-Api-Version": "2022-11-28" },
    body: JSON.stringify({ ref: "main" }),
  });
  return r.status;   // 204 = started. Never log the token or the response body.
}

export default {
  async scheduled(event, env, ctx) {
    if (!shouldDispatch(new Date(event.scheduledTime))) return;
    const status = await dispatch(env);
    console.log(`dispatch status ${status}`);
  },
  async fetch() { return new Response("unshaken-trigger: alive", { status: 200 }); },
};
