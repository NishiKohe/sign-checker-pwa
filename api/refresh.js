const REPO = 'NishiKohe/sign-checker-pwa';
const WORKFLOW = 'collect.yml';
const ALLOWED_ORIGINS = new Set([
  'https://nishikohe.github.io',
  'https://sign-checker-pwa.vercel.app'
]);

function githubHeaders(token) {
  return {
    Accept: 'application/vnd.github+json',
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-GitHub-Api-Version': '2022-11-28'
  };
}

export default async function handler(req, res) {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'OPTIONS') return res.status(204).end();

  const token = process.env.GITHUB_ACTIONS_TOKEN;

  // Safe health check. Never returns the token itself.
  if (req.method === 'GET') {
    return res.status(200).json({
      ok: true,
      endpoint: 'sign-checker-refresh',
      tokenConfigured: Boolean(token)
    });
  }

  if (req.method !== 'POST') return res.status(405).json({ ok: false, error: 'Method not allowed' });

  if (origin && !ALLOWED_ORIGINS.has(origin)) {
    return res.status(403).json({ ok: false, error: 'Origin not allowed' });
  }

  if (!token) {
    return res.status(503).json({ ok: false, error: 'GITHUB_ACTIONS_TOKEN not configured' });
  }

  try {
    // Do not start overlapping collectors. Also rate-limit repeated button taps.
    const runsResponse = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/runs?branch=main&per_page=1`,
      { headers: githubHeaders(token) }
    );

    if (runsResponse.ok) {
      const runsPayload = await runsResponse.json();
      const latest = runsPayload.workflow_runs?.[0];
      if (latest) {
        const recentMs = Date.now() - Date.parse(latest.created_at || 0);
        const running = ['queued', 'in_progress', 'waiting', 'pending'].includes(latest.status);
        const justStarted = Number.isFinite(recentMs) && recentMs >= 0 && recentMs < 5 * 60 * 1000;
        if (running || justStarted) {
          return res.status(200).json({
            ok: true,
            status: running ? 'already_running' : 'recently_started',
            runId: latest.id,
            createdAt: latest.created_at
          });
        }
      }
    }

    const response = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: 'POST',
        headers: githubHeaders(token),
        body: JSON.stringify({ ref: 'main' })
      }
    );

    if (response.status !== 204) {
      const detail = await response.text().catch(() => '');
      return res.status(502).json({
        ok: false,
        error: 'GitHub Actions start failed',
        status: response.status,
        detail: detail.slice(0, 300)
      });
    }

    return res.status(202).json({
      ok: true,
      status: 'triggered',
      startedAt: new Date().toISOString()
    });
  } catch (error) {
    return res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : 'Refresh failed'
    });
  }
}
