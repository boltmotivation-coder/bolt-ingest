# Setup (your username is already baked in)

Repo: boltmotivation-coder/bolt-ingest. No CHANGE-ME edits needed.

## Fix the repo (one paste in Terminal)

From the folder where you unzipped this:

    cd bolt-ingest
    git init -b main
    git add .
    git commit -m "bolt v1.0.0"
    git remote add origin https://github.com/boltmotivation-coder/bolt-ingest.git
    git push -f origin main

The -f overwrites the flat upload that's there now.

## Install commands for editors

Mac:

    curl -fsSL https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.sh | bash

Windows (PowerShell):

    irm https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.ps1 | iex

Run once, then `bolt` works. Test it on your own machine first with `bolt --dry-run` and a real Aaradhya block.

## Updates from now on

Fix a file (Claude Code or paste from chat), bump the version in BOTH bolt_ingest/__init__.py and pyproject.toml (1.0.0 -> 1.0.1), commit, push. Editors auto-update next time they run bolt.

## Optional webhook

Discord: Server Settings -> Integrations -> Webhooks -> New Webhook, copy URL. Each editor runs `bolt config`, option 2, pastes it. You get a ping with every pull: who, what, resolution, codec.
