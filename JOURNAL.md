# Journal

## 2026-11-14 — Thunderbird click-to-draft button + print-check tool

### Context
Branch `feat/pdf-check` was rebased onto `origin/main` (one conflict resolved in
`skills/pdf-check/SKILL.md`, merging both sides' doc additions). Goal for the session: replace
the always-on IMAP watcher with a Thunderbird toolbar button (ThunderAI-style) that generates a
draft on demand for whichever message is open, then extend the agent so it can also check
print-file attachments using the existing `pdf-check`/`margin-check` skills.

### 1. Harness: watcher → on-demand HTTP endpoint
- Added `harness/src/api/server.py`: stdlib `http.server`, `POST /draft` takes a raw email,
  runs it through the (unchanged) `skill_prompt`/`agent_loop`/`providers` pipeline, appends the
  draft to IMAP Drafts. No auth — security boundary is binding to `127.0.0.1` only.
- Deleted `mail_listener/watcher.py` and `state.py` (IDLE/poll loop, UID de-dup) — nothing needs
  them once there's no background loop.
- Trimmed `mailbox.py`: removed `select_folder`/`fetch_new`/`FolderInfo`/`FetchedMessage` (only
  the watcher used them); kept `extract_plain_text`, `build_draft_mime`, `connect`,
  `append_draft`.
- `Config`: dropped `detection_mode`/`poll_interval_seconds`/`state_file`/`inbox_folder`; added
  `api_host`/`api_port`.
- `main.py`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `README.md`/`ARCHITECTURE.md`
  updated to match. Tests updated/added accordingly (`test_harness_server.py` new,
  `test_harness_watcher.py`/`test_harness_state.py` deleted).

### 2. Thunderbird extension (`thunderbird-extension/`)
- `manifest.json` (MV2): `message_display_action` button, no popup so `onClicked` fires
  directly; `background.js` grabs the open message's raw source via
  `messenger.messages.getRaw()`, POSTs it to the harness, badges success/error, notifies on
  failure. Options page stores the backend URL.
- Packaged as `szkic-ai.xpi` (plain `zip`) and installed via Thunderbird's **Install Add-on
  From File** — confirmed Thunderbird, unlike Firefox, doesn't enforce AMO signing, so this
  installs permanently with no dev workaround needed.

### 3. Bug found during install: Docker loopback binding
`API_HOST` defaulted to `127.0.0.1`, which the server bound *inside* the container — but
Docker's port-forwarding delivers traffic to the container's external interface, not its own
loopback, so the published port was unreachable (`NetworkError` in Thunderbird, "connection
reset by peer" from `curl`). Fixed by setting `API_HOST=0.0.0.0` as a `docker-compose.yml`
environment override; the real security boundary stays `ports: ["127.0.0.1:8765:8765"]`
(host-side loopback-only publish). Documented the reasoning inline in both files so it isn't
"fixed" back to `127.0.0.1` later.

**Side-effect to flag**: while diagnosing this, a `curl` connectivity check accidentally ran
the *real* pipeline (real Claude API call + a junk draft appended to the real Drafts folder)
instead of just testing reachability. User was told to delete that draft manually. Lesson: don't
poke `/draft` directly for connectivity checks — use a path that 404s instead (done for all
later checks).

### 4. Open question: 51 pre-existing drafts
User found ~51 drafts in the Drafts folder and asked why. Confirmed from the code that the
on-demand endpoint only ever processes exactly one message per click (no inbox scanning, no
loop) — so today's button clicks can't explain 51. Best explanation offered: leftover from the
*old* always-on IDLE/poll watcher from an earlier session (it would have auto-drafted every new
inbox email the whole time it was running, unattended). Not independently confirmed — user was
asked to check timestamps/subjects on those drafts to tell "old backlog" apart from "something
still looping today." **Unresolved** — revisit if the user reports back.

### 5. Design discussion: why not a full Claude-Code-style agent
User asked why the harness doesn't give the model full tool access (Read/Bash/Skill) the way
Claude Code does. Answer: the harness currently gives the model exactly one tool
(`create_draft`) by design, because it processes **untrusted customer-supplied text**
unattended — fewer tools means a smaller prompt-injection surface. User pointed out the flow is
now human-triggered per email (not a 24/7 autonomous loop), and asked to loosen this. Agreed
partially: human-triggering removes the "runs unattended on whatever lands at 3am" risk, but
*not* the risk that the email body itself (still attacker-controlled) could try to steer a
more-capable agent — the human approves "draft a reply to this email," not whatever the agent
might do with extra tools. Scoped the actual change to: give the agent access to
**`pdf-check`/`margin-check` only**, not general filesystem/bash access (full Agent-SDK swap
explicitly declined as a non-goal for now).

### 6. Harness: `check_print_file` tool
- Added `harness/src/agent/print_check.py`: `check_print_file` tool, schema's `product` field
  is an `enum` of real product IDs from `rules.yaml`. Dispatches by extension — `.pdf` →
  `check_pdf.check_pdf` (product optional, PDFs self-describe their size) imported directly as
  a library call (no subprocess); `.jpg/.jpeg/.png/.tif/.tiff` → `check_image.check_file`
  (product **required** — image files don't know their own mm size).
- Tool description explicitly tells the model it has **no access to the generated preview
  image** (unlike the interactive `print-checker` Claude Code agent, which can view it) — so it
  must set `needs_human=true` and list specifics in `staff_notes` for any `SPRAWDŹ`/
  `OSTRZEŻENIE` result instead of guessing.
- `mailbox.py`: added `extract_attachments()`.
- `skill_prompt.py`: `build_system_prompt`/`build_user_message` take optional
  `has_attachments`/`attachment_filenames` so the model learns what's attached and that the
  tool exists, only when relevant.
- `server.py`: offers `check_print_file` alongside `create_draft` only when the incoming email
  actually has attachments.
- `harness/requirements.txt`: added `Pillow`, `numpy`, `pypdf`, `pypdfium2` — the container
  would otherwise crash on import (these scripts need them, and they weren't in the harness's
  own dependency list, only the top-level project's).
- Tests: new `test_harness_print_check.py` (real tiny PDF/PNG fixtures via `pypdf`/`PIL`, not
  mocked — proves the actual dispatch/import wiring works, not just the glue), plus coverage
  added to `test_harness_mailbox.py` (`extract_attachments`) and `test_harness_skill_prompt.py`
  (new prompt params). Full suite: 674 passed / 8 skipped at session end.

### Not done yet / follow-ups
- End-to-end click-through test with a real attachment through the live pipeline (would cost a
  real API call + write a real draft — left for the user to trigger intentionally).
- The 51-drafts question (see §4).
- Possible future options discussed but not built: live compose-window insertion instead of
  silent Drafts-folder save; keeping the old watcher as a second switchable mode; full
  Agent-SDK-style tool access (Read/Bash/Skill) if the scoped print-check tool turns out to be
  too narrow.

## 2026-11-18 — Generic skill loading, real script execution, step logging, git recovery

### Context
User asked why only one skill (`odpowiedzi-klientom`) ever seemed to get read. Root cause:
`skill_prompt.build_system_prompt()` hardcoded `scripts/odpowiedzi.py`'s `build_prompt()` as the
entire system prompt; `pdf-check`/`margin-check` were only reachable through `print_check.py`'s
direct library calls (never read their `SKILL.md`), and `wycena` wasn't wired in at all. User
wanted parity with how OpenClaw/Claude Code load skills: discover all of them, index them
lightly, load one's full content only on demand.

### 1. Generic skill registry (OpenClaw-style)
- New `harness/src/agent/skills_registry.py`: `discover_skills()` scans `skills/*/SKILL.md`
  frontmatter; `render_available_skills()` builds a `<available_skills>` name+description index
  injected into every prompt; `read_skill(name)` returns a skill's full instructions on demand —
  `odpowiedzi-klientom` still gets the old bundled SKILL.md+fakty.yaml+templates text (no file
  Read tool exists for the model, so this one has to arrive pre-bundled), the other three get
  their raw `SKILL.md` body plus a short "how this works in the harness, not Claude Code" note.
  `read_skill` tool (enum built from real discovered names) is always offered.
- New `agents/harness-agent.md` (project root, same frontmatter+markdown shape as
  `.claude/agents/print-checker.md`): single source of the base system prompt now, replacing
  the old `_GENERIC_INSTRUCTIONS`/`_TOOL_INSTRUCTIONS` strings in `skill_prompt.py`.
- `skill_prompt.build_system_prompt()` dropped its `use_skill: bool` parameter entirely —
  `Config.use_skill`/`USE_ODPOWIEDZI_SKILL` removed from `config.py`/`.env.example`/`README.md`.

### 2. Real script execution: `run_skill_script`
User pushed back when told "the harness can't run skill scripts" — correctly: that's the whole
point of a skill. Rather than full Bash (would reopen the exact prompt-injection surface the
2026-11-14 session deliberately declined), added a **scoped** tool: new
`harness/src/agent/run_script.py`, `run_skill_script(skill, script, args, input_text)` — runs
only allowlisted scripts (`wycena.py`, `canva_link.py`; `check_pdf.py`/`check_image.py`
deliberately excluded, since `check_print_file` already handles real binary attachments more
simply) via `subprocess.run([sys.executable, path, *argv], shell=False)` — argv list, no shell
string, 45s timeout, 20k-char output truncation. `input_text` writes to a temp file whose path
becomes the script's leading positional arg (covers `wycena.py <zamowienie.json>`); cleaned up
after. This is the first time `wycena`'s pricing API and Canva-link checking are reachable from
the harness at all. Verified live: `wycena.py --papers` against no running pricing app returns a
clean `Connection refused` message + exit code 3 as plain text (not an exception) — exactly the
shape the agent is told to turn into `needs_human=true` instead of inventing a price.

### 3. Agent-loop step logging
Added `INFO` logging in `agent_loop.py` (logger `harness.agent_loop`): one line per turn
(stop reason, tool names called, truncated model text) and one line per tool executed
(name/id, OK/BŁĄD, truncated result) — visible in normal container logs with no extra config,
since `main.py` already calls `logging.basicConfig(level=INFO)`.

### 4. Skill dry-run + wycena scope clarified
Drafted a real reply (via the `odpowiedzi-klientom` skill) to a sample canvas-print inquiry —
correctly used the `obrazy-sklep` template + the `terminy.obrazy_na_plotnie` fact, did **not**
invent a price. Confirmed `wycena` explicitly excludes canvas/wide-format/engraving/photobooks/
die-cut stickers (`poza_wycena` list in `SKILL.md`) — those go through `odpowiedzi-klientom`'s
templates instead. Gave a `wycena`-eligible example (wizytówki with all required fields) and
actually ran it through `run_skill_script` — got the real `Connection refused` failure since the
pricing app isn't running anywhere reachable yet.

### 5. `GRAFFAI_WYCENA_URL` / pricing app is external, not in this repo
Confirmed the real pricing service (`print_pricing` module, `POST /v1/quote`,
`docs/wycena-pytania.md`) isn't part of this repository at all — someone else owns/runs it.
`demo/wycena.js`/`demo.html` is a static, client-side-only preview page (explicitly says "Strona
NIE liczy ceny" in its own header) — not a server, unrelated to `GRAFFAI_WYCENA_URL`. User needs
to find out from their colleague where that service actually runs. Gave the Docker networking
decision tree for whichever answer comes back (`host.docker.internal`, same-compose-network
service name, or a remote host — each with different `GRAFFAI_WYCENA_URL` values).

### 6. Can the `.xpi` alone be shared with a client?
No — `thunderbird-extension/manifest.json`'s `permissions` only grants `http://127.0.0.1/*`, so
the installed extension can **only** ever reach a harness running on the same machine as the
client's Thunderbird, regardless of what URL is typed into the options page. Client needs: the
`.xpi`, enough of the repo to build/run the harness themselves (`harness/`, `skills/`,
`scripts/`, `agents/`, `docker-compose.yml`, `.env.example`), and their **own** `.env`
(IMAP credentials + `AI_API_KEY`) — not the whole repo, but not just the `.xpi` either.

### 7. Git incident: stash + branch-from-wrong-base, fully recovered
User ran `git stash` on `feat/pdf-check` (tip `2f1d411`), then created
`feat/harness-as-thunderbird-extension` pointing at a much older commit (`b3b32af`, 13 commits
behind `origin/main`, not in `feat/pdf-check`'s line) instead of renaming the branch in place.
Checking out that old commit deleted every tracked file only present in the newer history
(`harness/src/agent/providers/*`, all four `skills/*`, `pyproject.toml`, `uv.lock`, `demo/`,
`docs/`, etc.); `git stash pop` then conflicted on top of that. No `MERGE_HEAD` was ever set
(not a real merge), and the original stash object was never dropped, so nothing was at risk.
Recovery, in order: resolved the stash conflicts by staging the already-correct on-disk content
for the 16 directly-conflicted files; re-pointed the branch via `git reset --soft 2f1d411`
(blocked the first time — "cannot soft reset mid-merge" — so conflicts had to be resolved
first); a second, broader `git stash push`/`reset --hard 2f1d411`/`stash pop` cycle was needed
because the first stash-pop had reintroduced the *entire* old/new tree mismatch, not just the
16 files (a pathspec-limited `git stash push -- <paths>` turned out not to scope the saved
stash's content the way expected); re-did the intentional `mail_listener/watcher.py`/`state.py`
deletion that `reset --hard` had silently undone along the way. Final state: branch correctly
sits at `2f1d411` (equivalent to what a plain rename would have given), verified via the full
test suite (575 passed on everything this session's work touches). `feat/pdf-check` itself was
never touched.

**Found while recovering, pre-existing and unrelated to this session's work — left alone, not
fixed:**
- `skills/margin-check/scripts/margins.py` has an uncommitted, half-finished refactor (-129
  lines) that removed `panel_product`, but `skills/pdf-check/scripts/pdf_margins.py` still calls
  it — `AttributeError`, breaks 20 tests in `test_pdf_margins.py`/`test_przypadki_drukarni.py`.
- `.gitignore` has an uncommitted change that *removes* `.env` and `pylibs/` from the ignore
  list — worth fixing before anyone runs `git add -A`, since `.env` holds IMAP/AI API
  credentials.

### Not done yet / follow-ups
- `GRAFFAI_WYCENA_URL` still points at nothing reachable — blocked on the user finding out from
  their colleague where the real pricing app runs.
- The two pre-existing issues in §7 above (`margins.py`/`panel_product`, `.gitignore`) — user
  was asked, hasn't decided yet.
- `feat/pdf-check` (old branch) still exists alongside the renamed one; not deleted.
- Full `wycena` quote flow (`run_skill_script` → real price) has never been exercised against a
  live pricing app — only the connection-refused failure path is verified so far.
