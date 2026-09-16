export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', 'https://nishikohe.github.io');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false });
  }

  const token = process.env.GITHUB_ACTIONS_TOKEN;

  if (!token) {
    return res.status(503).json({
      ok: false,
      error: 'GITHUB_ACTIONS_TOKEN not configured'
    });
  }

  const response = await fetch(
    'https://api.github.com/repos/NishiKohe/sign-checker-pwa/actions/workflows/collect.yml/dispatches',
    {
      method: 'POST',
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28'
      },
      body: JSON.stringify({ ref: 'main' })
    }
  );

  if (response.status !== 204) {
    return res.status(502).json({
      ok: false,
      error: 'GitHub Actions start failed',
      status: response.status
    });
  }

  return res.status(202).json({
    ok: true,
    status: 'triggered'
  });
}
