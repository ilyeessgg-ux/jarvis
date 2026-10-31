# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's **Security → Report a
vulnerability** advisory form for this repository. Do not open a public issue
for anything that could expose a user's API key, conversation data, or machine.

## Local API

J.A.R.V.I.S. binds to `127.0.0.1` by default and its HTTP API has no
authentication. Do not expose the port to a network or the internet. If you
change `JARVIS_HOST`, put a firewall or authenticated reverse proxy in front of
it.

## API keys and data

- `OPENROUTER_API_KEY` lives in `.env` and is never sent to the HUD.
- `.env`, conversation databases, logs, and local models are git-ignored.
- If a key is exposed, revoke it at <https://openrouter.ai/settings/keys> and
  replace it in `.env`.

## Packaged builds

Release executables are built from this repository by the GitHub Actions
workflow in `.github/workflows/build-windows.yml`. They are not code-signed;
verify that downloads come from the official releases page.
