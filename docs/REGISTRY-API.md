# Registry API

The registry is a set of static JSON files. There is no server to run, no key to
request, and no rate limit beyond the host's own. Anything that can read a URL —
an agent, a script, another marketplace — can use it.

Base: `https://beko2210.github.io/SkillQuarry/`

| Endpoint | What it returns |
|---|---|
| `.well-known/skillquarry.json` | Discovery: where the registry, the archives, the docs and the client are |
| `api/v1/skills.json` | Every skill, with versions, checksums, security surface, dependencies and verifications |
| `api/v1/skills/<name>.json` | One skill, plus its version history |
| `registry.json` | The same list, kept at the old path for existing readers |

## Discovery

An agent that knows only the host starts here:

```bash
curl -s https://beko2210.github.io/SkillQuarry/.well-known/skillquarry.json
```

```json
{
  "name": "SkillQuarry",
  "registry": "https://beko2210.github.io/SkillQuarry/api/v1/skills.json",
  "archive_base": "https://github.com/BEKO2210/SkillQuarry/releases/latest/download",
  "documentation": "https://github.com/BEKO2210/SkillQuarry/blob/main/docs/REGISTRY-API.md",
  "client": "https://github.com/BEKO2210/SkillQuarry/tree/main/cli"
}
```

## Reading the list

```bash
curl -s https://beko2210.github.io/SkillQuarry/api/v1/skills.json | jq '.skills[] | {name, version, quality}'
```

Each entry carries what a decision needs before anything is downloaded:

| Field | Meaning |
|---|---|
| `name`, `displayName`, `version`, `description` | Identity |
| `category`, `quality`, `license`, `maintainers` | Classification and who is responsible |
| `compatibility`, `platforms`, `requires` | Where it runs and what it needs installed |
| `tests` | How many tests, what coverage, where the report is |
| `security` | Network reach, credentials, writes outside the repository, irreversible operations, threat model, reviewer |
| `dependencies`, `composes_with` | What must be installed first, and what it is designed to work alongside |
| `verifications` | Independent checks: who, when, how, what came out |
| `checksum` | SHA-256 over every file a user would install |
| `path` | Where the source lives in the repository |

## Fetching a skill

Archives live on the release named in `archive_base`, one per skill and version:

```bash
curl -sLO https://github.com/BEKO2210/SkillQuarry/releases/latest/download/cordon-1.0.0.tar.gz
```

Three independent checks are available, and they answer different questions:

```bash
# 1. Did the bytes arrive intact?
curl -sLO https://github.com/BEKO2210/SkillQuarry/releases/latest/download/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing

# 2. Did GitHub's own build produce them, from this repository?
gh attestation verify cordon-1.0.0.tar.gz --repo BEKO2210/SkillQuarry

# 3. Do the unpacked files match what the registry describes?
#    This is what the client does before it runs anything.
skillquarry install cordon --registry https://beko2210.github.io/SkillQuarry/api/v1/skills.json
```

The third check is the strongest: the archive is unpacked to a temporary
directory, hashed the same way the registry hashes a skill, and compared. A
mismatch stops the install before any script runs.

## Using another registry

The client reads any registry that answers with the same shape:

```bash
skillquarry --registry https://skills.example.internal/api/v1/skills.json list
skillquarry --registry https://skills.example.internal/api/v1/skills.json install my-skill
```

Or set it once:

```bash
export SKILLQUARRY_REGISTRY=https://skills.example.internal/api/v1/skills.json
export SKILLQUARRY_TOKEN=…        # sent as: Authorization: Bearer …
```

HTTPS is required. A registry decides what code ends up on a machine, so the
client refuses plain HTTP rather than trusting whoever is on the path.

Running your own: [docs/SELF-HOSTING.md](SELF-HOSTING.md).

## Stability

`api/v1/` will not change shape. Fields may be **added**; existing fields keep
their meaning. A breaking change becomes `api/v2/`, and `v1` keeps working until
it is announced otherwise. `registry.json` at the root is the pre-v1 path and is
kept as an alias.
