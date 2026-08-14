# Running your own quarry

A registry is static files. Hosting one means serving a directory over HTTPS —
no database, no application server, nothing to keep alive but a web server.

This is what you need for a **private** registry: skills that must not be public,
on a machine your people can reach and nobody else can.

## What you serve

```text
<web root>/
├── .well-known/skillquarry.json     discovery
├── api/v1/skills.json               the registry
├── api/v1/skills/<name>.json        one file per skill
└── archives/
    ├── <name>-<version>.tar.gz      one per skill and version
    └── SHA256SUMS
```

Generate the first three from your own checkout:

```bash
python3 tools/render_readme.py     # registry/skills.json
python3 tools/build_site.py        # site/, including api/v1 and .well-known
python3 tools/package_skills.py    # dist/, the archives and their checksums
```

Then publish `site/` as the web root and `dist/` as `archives/`, and set
`archive_base` in your registry document to wherever the archives ended up.

## Serving it

Anything that serves files works. A container with a static server is enough:

```bash
docker run -d --name skillquarry \
  --restart unless-stopped \
  -v /srv/skillquarry/site:/usr/share/nginx/html:ro \
  -p 127.0.0.1:8090:80 \
  nginx:alpine
```

Bind to `127.0.0.1` and put your existing reverse proxy or tunnel in front of it,
so the port is not exposed on the LAN by accident. If Docker is involved, remember
that a published port bypasses UFW.

For a registry that should only exist inside your own network, bind to the
private-network address instead of `0.0.0.0` and skip the public tunnel entirely:
the client reaches it over the VPN like any other host.

## Pointing the client at it

```bash
export SKILLQUARRY_REGISTRY=https://skills.example.internal/api/v1/skills.json
skillquarry list
skillquarry install my-skill
```

If the registry requires authentication, the client sends a bearer token:

```bash
export SKILLQUARRY_TOKEN=…
```

Configure your proxy to require that header. The token is only ever sent to the
registry host, and never written to the install record.

## HTTPS is not optional

The client refuses plain HTTP. A registry determines which code lands on a
machine; over HTTP anyone on the path chooses that code. Use a certificate — a
private CA is fine, as long as the machines trust it.

## What still protects you

Nothing about self-hosting weakens the checks:

- the archive is unpacked to a temporary directory and hashed before anything runs;
- the hash must equal the `checksum` in your registry, or the install stops;
- the skill's own installer runs only after that, and only it decides what to write.

What self-hosting **does not** give you is GitHub's build provenance. Public
archives can be verified with `gh attestation verify`; your own archives are only
as trustworthy as the machine that built them. Build them in a pipeline you
control and keep the checksums under review.

## Keeping it current

The registry is regenerated from the manifests, so a cron job is enough:

```bash
cd /srv/skillquarry/checkout
git pull --ff-only
python3 tools/validate_skills.py
python3 tools/render_readme.py
python3 tools/build_site.py
python3 tools/package_skills.py
rsync -a --delete site/ /srv/skillquarry/site/
rsync -a --delete dist/ /srv/skillquarry/site/archives/
```

Run `python3 tools/registry.py verify` afterwards: it recomputes every checksum
and fails if the registry describes files that are no longer there.
