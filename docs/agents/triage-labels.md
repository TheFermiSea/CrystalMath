# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual
label strings used in this repo's issue tracker (**beads** — applied with `bd label add <id> <label>`).

| Label in mattpocock/skills | Label in our tracker (`bd`) | Meaning                                  |
| -------------------------- | --------------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`              | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`                | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`           | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`           | Requires human implementation            |
| `wontfix`                  | `wontfix`                   | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), apply the corresponding
`bd` label with `bd label add <id> <label>`.

Beads tracks **status** (`open`, `in_progress`, `blocked`, `closed`, `deferred`) and **priority**
(`P0`–`P4`) independently of these triage labels — the labels above are the triage state machine, not
a replacement for status/priority. (`bd label set-state` can also record an operational state event
if you prefer state-as-event semantics.)

Edit the right-hand column to match whatever vocabulary you actually use.
