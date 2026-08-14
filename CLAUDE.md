# SkillQuarry

Marketplace fuer Agent-Skills. Live: https://beko2210.github.io/SkillQuarry/
Registry-API: `https://beko2210.github.io/SkillQuarry/api/v1/skills.json`
Wer hier arbeitet, liest diese Datei und kartiert **nicht** neu.

## Aufbau

```
skills/<kategorie>/<name>/   ein Skill: skill.json, SKILL.md, README.md,
                             TEST_REPORT.md, install.sh, uninstall.sh,
                             src/, tests/ (run_tests.py ist der Einstieg)
tools/                       Generatoren und deren Tests
cli/skillquarry.py           der Client (eine Datei, nur Stdlib)
registry/ site/ README.md    GENERIERT — nie von Hand anfassen
assets/                      SVG-Logos/-Banner (Hand), img/ (Higgsfield), video/
.github/workflows/           checks, pages, release, je Skill ein Test-Workflow
```

Skills: `strata` (autonomous), `cordon` + `rangate` (security),
`lockscope` (coding). Kategorien-Enum steht in `registry/schema.json`.

## Die eiserne Regel: generiert wird generiert

`README.md` (Marker-Bloecke), `registry/skills.json`, `registry/history.json`
und `site/` entstehen aus den `skill.json`-Manifesten. Nach **jeder** Aenderung
an einem Skill:

```bash
python3 tools/render_readme.py && python3 tools/build_history.py && python3 tools/build_site.py
```

CI (`checks`) laesst jeden Commit durchfallen, dessen generierte Dateien nicht
aktuell sind — auch die **Pruefsumme** in der Registry haengt an jedem Byte des
Skill-Ordners. Eine Skill-Datei aendern ohne neu zu rendern = roter Commit.
`--check` auf allen dreien prueft, ohne zu schreiben. `build_history` braucht
volle Git-Historie (CI: `fetch-depth: 0`).

## Site

- `tools/build_site.py` ist die **einzige Quelle** (frueher aus drei
  Scratchpad-Teilen zusammengesetzt — das ist Geschichte, direkt editieren).
- Stylesheet-URL traegt einen Inhalts-Fingerprint (`style.css?v=<hash>`),
  Cache-Probleme sind damit erledigt; der Hash folgt STYLE automatisch.
- Kachel-Abstand ist `padding` der Karte selbst; nur `.art` ragt per negativem
  Rand an den Rand. Nie wieder ueber Kind-Margins bauen (Test erzwingt das).
- Goldener Schnitt-Skala `--s1..--s7` (8/13/21/34/55/89/144), Handy zentriert.
- Kontrast: hell und dunkel getrennt messen; WCAG AA 4.5:1 fuer Kleintext
  (`--dim` hell = #546d85 ist genau deshalb dunkler als dunkel-Theme-dim).
- Hero-Video ist ein Palindrom (endet wo es anfaengt); Naht gemessen gleich
  einer normalen Frame-Bewegung. Neues Video nur als Palindrom bauen:
  ein Filtergraph `split/reverse/concat`, NIE `-c copy` mischen.
- Downloads-Zaehler auf den Karten = GitHub-Release-Asset-Zaehler. Ein Skill
  ohne Release-Archiv zeigt nichts → Release schneiden.
- Test: `python3 tools/test_build_site.py`. QS-Sweep bei UI-Aenderungen:
  Viewports 360/390/414/768/1024/1440, kein horizontales Scrollen, Text nie
  <10px am Kachelrand, Buttons >=40px und am Handy zentriert.

## Release

```bash
git tag skills-YYYY.MM.DD[suffix] -m "..." && git push origin <tag>
```

Workflow `release` baut reproduzierbare Archive (`<skill>-<version>.tar.gz`),
SHA256SUMS und Build-Attestation. `archive_base` der Registry zeigt auf
`releases/latest/download` — nach Skill-Aenderungen **muss** ein neues Release
folgen, sonst verweigert der Remote-Install (Registry-Pruefsumme passt nicht
mehr zum alten Archiv). Version nicht pro Lauf erhoehen; ein Release buendelt.

## Client

`cli/skillquarry.py`: search/info/install/uninstall/update/validate/doctor,
remote via `--registry`/`$SKILLQUARRY_REGISTRY`, HTTPS-Pflicht, verifiziert
Archiv gegen Registry-Pruefsumme vor dem Installer des Skills. Installierte
Quellen liegen unter `~/.local/state/skillquarry/sources/`, damit uninstall/
update ohne Checkout gehen. Tests: `cd cli && python3 tests/run_tests.py`
(100% Abdeckung halten). Skill-Listen in Tests aus der Registry ableiten,
nie hart verdrahten.

## Neuer Skill

1. `python3 tools/new_skill.py` bzw. an `skills/security/cordon/` orientieren.
2. skill.json vollstaendig (Schema `registry/schema.json`); ehrliche
   `security`-/`permissions`-Angaben; `tests.report` muss existieren.
3. Eigener Workflow `.github/workflows/<name>-tests.yml`; Skips sind dort
   Fehler (Muster: `LOCKSCOPE_REQUIRE_TOOLCHAIN`).
4. Logo+Banner-SVG in `assets/` (Palette: Grund #0d141b/#1c2733, Linie
   #ffd479→#f0932b), Karte+3D-Icon via Higgsfield (`gpt_image_2`) nach
   `assets/img/<name>-card.webp` (960x542) und `icon-<name>.webp` (512x512);
   Icon wird ueber Namenskonvention gefunden, Karte via `"image"` im Manifest.
5. Generatoren laufen lassen, Release schneiden.

## LockScope-Besonderheiten

Pinnings sind Beweisgrundlage: rustc/cargo/rust-analyzer 1.97.1,
tree-sitter 0.25.2, tree-sitter-rust 0.24.0, Fixture-Crates mit `=`-Versionen.
`drop(guard)` macht ein Future NICHT Send, Scope-Ende schon — Compiler-Proben
pinnen das. Reale Repos (Javis/Ferryman/mini-redis) an feste Commits gebunden;
mini-redis-Baseline ist bei striktem Clippy historisch rot → baseline-relativ
vergleichen. Forschungszweig `test/lockscope-v2-20260814` ist Beleg, behalten.

## Arbeitsregeln

- Messgeraet vor Code verdaechtigen; Behauptungen mit Befehlsausgabe belegen.
- Tests nie abschwaechen, um gruen zu werden; korrigierte Erwartungen im
  TEST_REPORT dokumentieren (dort steht auch, was CI alles gefangen hat).
- Erst lokal gruen, dann push; CI-Ergebnis abwarten und nennen.
- `main` direkt nur fuer kleine Fixes; ganze Skills ueber Branch + PR,
  Merge macht der Maintainer.
- Experimente, die ihr eigenes Gate reissen, kommen NICHT ins Repo
  (Praezedenz: CrypticShift — restlos entfernt).
