# Discord application profiles

Modral runs two Discord applications against the same backend and frontend images. The request hostname selects the OAuth application; the server ID selects the bot token used for server-scoped Discord REST calls.

| Surface | Dashboard | API | Discord application | Global reply command |
| --- | --- | --- | --- | --- |
| CyberColors | `https://cybercolors.modral.app` | `https://cybercolors-api.modral.app` | CyberColors | `Reply as CyberColors` |
| Modral | `https://dashboard.modral.app` | `https://api.modral.app` | Modral | `Reply as Modral` |

The legacy `cybercolors.lightny.pro` and `cybercolors-api.lightny.pro` pair remains mapped to CyberColors.

## Discord developer portal

Configure these OAuth redirects on the matching Discord applications:

- CyberColors: `https://cybercolors.modral.app/callback`
- Modral: `https://dashboard.modral.app/callback`

The two applications must each have the bot and `applications.commands` scopes. Global commands belong to the Discord application, so both applications can register their own reply command without per-guild command variants.

## Kubernetes credentials

The existing `cybercolors-app-secrets` Secret remains the compatibility source for CyberColors credentials. Before deploying the new worker, create the dedicated Modral Secret in the `cybercolors` namespace:

```sh
kubectl -n cybercolors create secret generic modral-discord-credentials \
  --from-literal=MODRAL_DISCORD_BOT_TOKEN='...' \
  --from-literal=MODRAL_DISCORD_CLIENT_ID='...' \
  --from-literal=MODRAL_DISCORD_CLIENT_SECRET='...'
```

Do not commit the real values. The `modral-bot` Deployment requires this Secret; the shared API and background workers load it when present.

## Rollout order

1. Add both redirect URIs in the Discord developer portal.
2. Create `modral-discord-credentials` in Kubernetes.
3. Apply migration `f3b4c5d6e7a8`.
4. Deploy the backend, frontend, shared workers, and both bot Deployments.
5. Invite the Modral application to a pilot server from `dashboard.modral.app`.
6. Verify `/auth/profile` on both API hosts, complete both login flows, and confirm each server appears only on its assigned dashboard.
7. Confirm the global message commands in Discord and check that both `cybercolors-bot` and `modral-bot` are Ready.

`CYBERCOLORS_GUILD_IDS` reserves the listed guilds for the CyberColors application. Every other guild is assigned to Modral. A gateway ignores messages and commands from a guild assigned to the other application, and dashboard requests redirect to the server's canonical surface.
