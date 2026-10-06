# BanterBox

Ultra-low-latency voice sports pundit spec for a hackathon build.

This repo is the **implementation-ready coding prompt**, not the app itself. Hand [`BANTERBOX_IMPLEMENTATION_SPEC.md`](./BANTERBOX_IMPLEMENTATION_SPEC.md) to a coding model and it should scaffold the FastAPI + Vite React MVP from a greenfield tree.

## GitHub repo name

Use this exact name (matches the local folder):

```
voice-agent-hack
```

## Push this folder to GitHub

From this directory, after creating an empty GitHub repo named `voice-agent-hack` (no README, no .gitignore, no license):

```bash
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/voice-agent-hack.git
git branch -M main
git push -u origin main
```

Or create the GitHub repo and push in one shot (GitHub CLI):

```bash
gh repo create voice-agent-hack --private --source=. --remote=origin --push
```

Drop `--private` if you want it public.

## What to build from

Open [`BANTERBOX_IMPLEMENTATION_SPEC.md`](./BANTERBOX_IMPLEMENTATION_SPEC.md) and run it as the system/user prompt for a coding agent. Follow it exactly: stack, file tree, WebSocket frames, tools, audio buffers, and spoken-first prompts are locked in that file.
