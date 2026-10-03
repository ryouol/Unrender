# Product management and delivery

Unrender's product backlog and delivery record are linked across:

- [ChatGPT product hub](https://chatgpt.com/space/page_dcf28fe76ecc81919d021f971a0fe5bd)
- [Notion product and delivery](https://app.notion.com/p/3ee69b28e04f810183d0e4574c0abecb)
- [GitHub repository](https://github.com/ryouol/Unrender)

The project pages are private coordination documents; their links do not grant access.
They do not add a runtime Notion dependency or a generic two-way synchronization service.

## Recurring PM work

The **Unrender weekly PM and delivery** automation runs in the existing Codex chat
on Mondays at 09:00 America/Toronto. The local computer must be available for local
coding steps. GitHub remains the source of truth for code and checks; the PM run
updates both project pages with evidence and links.

Each run:

1. Read current `origin/main`, open pull requests, the backlog, and recent release
   evidence. Resume unfinished work before creating duplicate changes.
2. Identify one concrete user problem, state the evidence, and define acceptance
   criteria. Prefer data integrity, review speed, and recovery improvements.
3. Implement in an isolated checkout. Preserve unrelated local changes.
4. Run meaningful regressions and the applicable repository checks. Record actual
   results, including unavailable checks.
5. Publish a focused pull request. Merge and deploy low-risk changes only after
   required checks and the [operations runbook](OPERATIONS.md) prerequisites pass.
6. Update both project pages, distinguishing implementation, tests, pull request,
   merge, and verified deployment. Report only meaningful changes or blockers.

The recurring task does not authorize customer-data migrations, model/provider
replacement, billable inference, billing changes, or new access permissions.
Those require a separately scoped request.

## Dot handoff

Direct assignment to Your dot is pending. No dot assignment or cloud execution is
implied by these links or the local automation. The current computer-use interface
blocks access to the ChatGPT desktop app, and no direct dot-assignment tool is exposed.

To hand off coordination, open the ChatGPT hub, select your dot from the mention
menu, and ask it to track the existing PM workflow and backlog. Reuse the existing
schedule rather than starting a second coding loop. See the official
[Space agent guide](https://learn.chatgpt.com/docs/space/agents) and
[dot task guide](https://learn.chatgpt.com/docs/dots/tasks-and-memory).

## First refinement

The October 3, 2026 PM review selected full-table editor validation: a missing
category/value must not silently delete a point, and an invalid series assignment
must not move it. Save and approval must preserve the draft and identify the row
that needs correction, including rows outside the visible editor page. Numeric x
values must survive scientific-notation round trips without changing type.

A follow-on candidate is adding a data series omitted by extraction. Validate that
need with representative charts before expanding editor controls.
