# hetzner-server-monit

Discord bot that watches dedicated server models on <https://robot.hetzner.com/order>
(fetched anonymously every 60s) and posts to Discord when a watched model becomes
available or sells out again.
Prices are shown in USD for a US customer (0% VAT): the bot submits the page's region form
(`currency=USD`, `country=US`) once per session.

## Commands

| Command | Effect |
|---|---|
| `/add <model>` | Watch a model (exact name, e.g. `AX42-1`, autocompleted from the page). Alerts go to the channel you ran it in. |
| `/remove <model>` | Stop watching. |
| `/list` | Watched models, current state, alert channel. |

## Discord setup

1. <https://discord.com/developers/applications> → **New Application** → **Bot** → **Reset Token**, copy it.
2. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`; bot permissions
   `Send Messages`, `Embed Links`. Open the URL and add the bot to your server.
   No privileged intents are needed.

## Deploy (k8s, no image build)

The code ships as a ConfigMap and runs on stock `python:3.13-slim`; an init container
`pip install`s `app/requirements.txt` at pod start. State (`focus` + last-seen) lives on a
100Mi PVC.

```sh
kubectl -n default create secret generic monit-discord --from-literal=DISCORD_TOKEN=<token>
kubectl apply -k .
```

After changing code, `kubectl apply -k .` again — the ConfigMap name hash changes and the pod rolls.

Env: `POLL_SECONDS` (default 60), `STATE_PATH`, `DISCORD_TOKEN`.

## Local

```sh
uv run --python 3.13 --with-requirements app/requirements.txt --with pytest pytest -q
DISCORD_TOKEN=<token> uv run --python 3.13 --with-requirements app/requirements.txt python app/main.py
```
