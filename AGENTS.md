# DesiMapper — Agent Notes

Project: `DesiMapper`

## Devin Setup

### Mempalace (knowledge base)
- CLI: `~/.local/share/mempalace-venv-parent/venv/bin/mempalace`
- Palace data: `~/.mempalace/` (default)
- Wing for this project: see `mempalace.yaml` in project root
- Search past context: `mempalace search "query"` or via the `mempalace_*` MCP tools
- Mining: `mempalace mine <project-dir> --mode projects` to re-index project files

### Global skills (available in every project)
- **caveman-mode** — terse output. Trigger: "caveman mode", "be terse", "no filler"
- **skill-creator** — meta-skill for authoring new skills

### Hooks (global, fire automatically)
- **Stop** — auto-mines conversation transcript every 15 exchanges into mempalace
- **PostCompaction** — re-mines project dir after context compaction

### MCP servers (global)
- **mempalace** — `mempalace_search`, `mempalace_list_wings` auto-approved
