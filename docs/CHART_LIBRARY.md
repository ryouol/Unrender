# Private chart library

Projects organize one account's charts. They do not grant sharing or membership
permissions. Each account can create at most 50 projects; project names allow
1–80 characters and chart display names 1–120 characters, without control
characters. Friendly names leave the original source filename unchanged.

All library routes require a browser session. Mutations also require its CSRF
header. API keys cannot create or change projects.

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/projects` | — | `{items: [project], limit: 50}` |
| `GET /api/projects/{id}` | — | One owned project; otherwise 404 |
| `POST /api/projects` | `{name}` | 201 project |
| `PATCH /api/projects/{id}` | `{name}` | Updated project |
| `PATCH /api/jobs/{id}` | `{display_name?, project_id?}` | Updated chart |
| `DELETE /api/uploads/{id}` | — | 204 removed, or 202 file cleanup queued |
| `DELETE /api/projects/{id}` | `?mode=keep_charts` | Project removed; its charts kept |
| `DELETE /api/projects/{id}` | `?mode=delete_charts&expected_chart_count=N` | Project and charts removed |

A project contains `id`, `name`, `chart_count`, `active_count`, `created_at`, and
`updated_at`. Chart JSON adds `display_name` and nullable `project_id`. Omit a
metadata property to preserve it; set `project_id` to null to remove assignment.
An empty metadata patch is rejected. Listing charts retains the existing cursor
pagination contract.

Project removal returns `{status, charts_deleted, charts_kept}`. `status` is
`deleted` or `deletion_queued`. Deleting chart contents requires a freshly shown
chart count; a changed count returns 409 `project_changed`. Queued or running
charts return 409 `project_busy` without deleting anything. Cancel them and wait
for a terminal state before trying again. Keeping charts is allowed while they
are active and moves them into unassigned My charts.

Deletion is permanent; there is no trash or undo. Database removal and source
deletion records commit together. Files are removed after commit, and transient
storage failures remain in the durable retry queue. A shared prepared upload
survives chart deletion while another chart references it. Explicitly discarding
a prepared upload revokes that original preview immediately while existing charts
keep their independent source copies. Backups follow their separate retention
policy and are not represented as instantly erased by these actions.

Schema 12 adds projects and nullable project assignment. Existing charts retain
their IDs, sources, results, credits, and sessions, and use the original filename
as their initial display name. The migration is atomic; older releases must not
be started against this schema. Follow the coordinated backup and restore
procedure in OPERATIONS.md when rolling back a schema-changing release.
