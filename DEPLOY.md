# Deploy Genie Live

This repo is now set up for a static Vercel deploy of:

- public landing page
- sample report preview
- static private portal preview page

## What this static deploy includes

- `/` serves the public landing page
- `/portal` serves a static preview of the private portal
- `sample-report.json` is served as a plain static asset
- the public form now generates a drafted clinic-email template in-browser

## What this static deploy does not include

- no live backend
- no access-request database
- no real portal authentication
- no file uploads
- no genomics pipeline execution on the public URL

That is intentional. This is the cheapest clean path to getting a real public website link live now.

## Files used by the Vercel deploy

- `vercel.json`
- `genie-landing.html`
- `genie-portal.html`
- `sample-report.json`
- `latest.mp4`

## Deploy on Vercel

1. Push the repo to GitHub.
2. In Vercel, create a new project from that GitHub repository.
3. Vercel will detect this as a static project automatically.
4. Deploy.

The included `vercel.json` rewrites:

- `/` -> `genie-landing.html`
- `/portal` -> `genie-portal.html`

## Public URL

After deploy, Vercel will give you a URL like:

- `https://genie-site.vercel.app`

You can attach a custom domain after that inside the Vercel project settings.

## Going from website-live to full-product-live later

When you want real uploads and report generation, you will need to move back to an app host or serverless/backend setup with:

1. a real backend
2. persistent storage
3. auth
4. Linux-compatible genomics dependencies
5. privacy/security review before accepting reproductive genomics uploads publicly
