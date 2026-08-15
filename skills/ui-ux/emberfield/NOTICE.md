# Notice

Emberfield is a derivative work of **algorithmic-art** from
[anthropics/skills](https://github.com/anthropics/skills), used under the
Apache License 2.0 (the full text ships in `LICENSE.txt`, unchanged).

Copyright for the original work: Anthropic, PBC.

## What was changed

As section 4(b) of the licence asks, the changes are stated:

- The skill was renamed to **Emberfield** and restyled: the original viewer
  carried Anthropic's own branding, colours and fonts, which the licence does
  not cover — trademarks stay with their owner — so the viewer was rebuilt in
  SkillQuarry's visual language with the same control contract (seed field,
  previous/next/random seed, parameter sliders, colour pickers, reset, PNG
  export).
- `SKILL.md` was rewritten in this repository's voice. The method is the
  original's: first an algorithmic philosophy, then its expression as seeded
  p5.js code.
- A test suite, an installer, a manifest and a worked example were added;
  none of these existed upstream.
- `templates/generator.js` is the upstream best-practices template with its
  guidance intact.

## What is not claimed

No endorsement by, affiliation with, or sponsorship from Anthropic is claimed
or implied. "Anthropic" and its marks belong to Anthropic, PBC.

p5.js is loaded by generated artworks from its public CDN and is not
redistributed here; it is licensed under the LGPL-2.1 by the Processing
Foundation.
