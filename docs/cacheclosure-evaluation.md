# CacheClosure evaluation note

CacheClosure 1.0.0 was promoted under a preregistered protocol rather than by
expanding its rules until every historical example passed.

The frozen set contains three historical cache defects. Version 1.0.0 recovers
the Kinesis Adv360 ZMK empty-`hashFiles` defect and the Zuban cached-sentinel
defect. It deliberately misses the Yapboard SwiftPM case because the omitted
causal input is runtime build metadata rather than repository-visible state.

Frozen release gates are recorded in
`skills/coding/cacheclosure/FROZEN_PROTOCOL.md`; exact upstream repair commits
and primary-source evidence are recorded in
`skills/coding/cacheclosure/RESEARCH.md`; observed results and integration
amendments are recorded in `skills/coding/cacheclosure/TEST_REPORT.md`.

No language model participates in the detector's oracle. The published scanner
reads repository files only, executes no analysed-repository command, uses no
network access, and does not modify the analysed repository.
