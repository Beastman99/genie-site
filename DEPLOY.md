# Deploy Genie Live

This repo is now set up for a first live deploy of the public site and private portal shell.

## What this deploy includes

- public landing page
- private portal login
- access-request collection
- sample report preview

## What this deploy does not include yet

The live deploy is configured with uploads disabled:

- `GENIE_ENABLE_PIPELINE=0`

That is intentional. The current public deployment path is for the website itself. The full genomics pipeline still needs heavier runtime dependencies and a more deliberate production setup before it should accept real uploads on the internet.

When uploads are disabled, the portal stays visible but clearly says that uploads are not enabled on that deployment.

## Files added for deployment

- `Dockerfile`
- `.dockerignore`
- `render.yaml`

## Recommended host

Use Render with the included Blueprint:

- docs: https://render.com/docs/web-services
- docs: https://render.com/docs/docker
- docs: https://render.com/docs/blueprint-spec
- docs: https://render.com/docs/disks

## Before you deploy

This folder is not currently a git repository. Make it one and push it to GitHub first:

```bash
cd "/Users/benjamineastman/Documents/genie/better genie"
git init
git add .
git commit -m "Prepare Genie site for live deployment"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

## Deploy on Render

1. Create a new GitHub repository and push this folder.
2. In Render, create a new Blueprint and point it at that repository.
3. Render will detect `render.yaml`.
4. Set a real `GENIE_PORTAL_CODE` value when prompted.
5. Deploy.

The Blueprint will create:

- one Docker web service
- one persistent disk mounted at `/app/data`

## Important environment variables

- `GENIE_PORTAL_CODE`
  - required for private portal entry
- `GENIE_ENABLE_PIPELINE`
  - `0` for public-site-only deploy
  - `1` only after the full upload pipeline is production-ready
- `GENIE_DATA_DIR`
  - where access requests and job data are stored
- `GENIE_COOKIE_SECURE`
  - should stay `1` on HTTPS production

## Health check

The app now exposes:

- `/healthz`

Example response:

```json
{
  "ok": true,
  "pipeline_enabled": false,
  "data_dir": "/app/data"
}
```

## Going from website-live to full-product-live

To enable real uploads later, you will need at minimum:

1. Linux-compatible `bcftools` / `tabix`
2. Linux-compatible `plink2`
3. job runtime and timeout strategy for longer scoring runs
4. stronger auth than one shared access code
5. a real persistent datastore for requests, jobs, and users
6. privacy/security review before accepting reproductive genomics uploads publicly

Do not flip `GENIE_ENABLE_PIPELINE=1` on the public deployment until those pieces are in place.
