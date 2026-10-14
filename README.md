# Cloud Tasks

Your iCloud Reminders and Google Tasks together in a native GTK4/libadwaita app
and a JSON CLI. The providers remain the source of truth. There is no second
local task database, notification daemon, or replacement for Ghost's Markdown
planning board.

## Install

Python 3.10+ runs the CLI without Python packages. Source installation also needs
Rust/Cargo to build the bundled private iCloud provider. For the native app, install
PyGObject, GTK4, and libadwaita (Omarchy/Arch: `omarchy pkg add python-gobject gtk4
libadwaita`). The iCloud backend ships with Cloud Tasks; only `icloud-session` remains shared.
Install `gws` for Google access. The retired icloud-reminders package is not needed.

```sh
git clone https://github.com/ferdousbhai/cloud-tasks.git
cd cloud-tasks
./install.sh
cloud-tasks --app
```

The source installer installs into `~/.local`, including an application-menu
entry, without sudo. Ensure `~/.local/bin` is on PATH. An optional first argument
sets another prefix. Re-run it after updating the checkout. There is an Arch
`packaging/PKGBUILD` for local builds; no published signed package repository yet.

## Link accounts

```sh
cloud-tasks account add icloud
cloud-tasks account add google --name work
cloud-tasks account list
```

iCloud reuses `icloud-session`; the protocol/sync backend belongs to Cloud Tasks. If needed,
run `icloud-session sign-in` yourself; the apps and shared sign-in come from
[icloud-for-omarchy](https://github.com/ferdousbhai/icloud-for-omarchy).

Install `gws` via `npm install -g @googleworkspace/cli` or an upstream release.
For a new Google account, configure a `gws` OAuth client in its isolated account
directory. The automated setup needs `gcloud`; manual setup is also documented
by [gws](https://github.com/googleworkspace/cli). Run auth in your own terminal:

```sh
GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/cloud-tasks/gws/work" gws auth setup
cloud-tasks account login work
```

Login requests only the Tasks scope. Enable the Tasks API in that client's
Google Cloud project. Never put credentials, OAuth callbacks, or recovery codes
in chat. To explicitly use an existing authorized account context:

```sh
cloud-tasks account add google --name personal --gws-config ~/.config/gws
```

Cloudmail/Cloud Calendar credentials are not reused or expanded implicitly.
Provider calls clear ambient token and credential-file overrides; `gws` manages
its encrypted credentials and file-backend encryption key. Native Accounts lets
you link, open terminal sign-in, and remove accounts. `account remove NAME`
previews; `--yes` unlinks without deleting provider data or credentials.

## Read and write

```sh
cloud-tasks status
cloud-tasks lists
cloud-tasks list
cloud-tasks list --all
cloud-tasks list --completed
cloud-tasks list --list 'work:<list-id>'
cloud-tasks show 'work:<task-id>'
cloud-tasks add 'Call the dentist' --list 'icloud:<list-id>' --due 'tomorrow 09:00'
cloud-tasks add 'Review report' --list 'work:<list-id>' --due tomorrow
cloud-tasks edit 'work:<task-id>' --notes 'Bring the figures'
cloud-tasks complete 'work:<task-id>'
cloud-tasks uncomplete 'work:<task-id>'
cloud-tasks delete 'work:<task-id>'
cloud-tasks delete 'work:<task-id>' --yes
```

Replace placeholders with exact opaque IDs from output. Task IDs encode both
the Google list and task identity; never guess or trim them. Creating a task
requires the destination list. Default list shows open tasks; all/completed are
explicit filters. Creation/edit/completion are writes; deletion previews until
`--yes`. A timeout may have happened after a write: inspect before retrying.

Every command emits `{ok, data, meta: {warnings}}`; `--json` is also accepted.
Failures return `{ok:false, error:{code,message,details}}` and exit nonzero.
Successful results can be incomplete: inspect warnings for failed accounts or
lists. If all selected accounts/lists fail, the command fails. Completed Google
tasks hidden by Google's own app are included when requested. Assigned tasks
are included; deleting an assigned Google task may also delete the original in
Docs/Chat, so consider that broader scope before deletion.

## Provider differences

- **Google supports due dates only.** `YYYY-MM-DD`, `today`, and `tomorrow` work.
  Due times, invalid dates, and other expressions are rejected before writing,
  never silently truncated. Tasks report `capabilities.due_time: false`.
- **iCloud supports due dates/times** through the bundled iCloud provider.
  Existing Apple alarms keep their own times when a due date changes; edits
  report a warning when alarms are present. Change those alarms on Apple devices.
- Recurrence, alarm configuration, list creation/deletion, list reordering, and
  moving tasks between providers are not exposed in this first version. Manage
  those through the provider apps. No automatic task copies or two-way sync
  engine; changes go directly to the selected source.

The desktop app offers search, include-completed filtering, task creation,
edits, completion/uncompletion, deletion confirmation, details, and account
management. It uses the same application layer and provider adapters as the CLI.
Cloud Tasks owns the Apple notification timer (see migration below).

## Agent skill

[skills/cloud-tasks/SKILL.md](skills/cloud-tasks/SKILL.md) teaches AI agents to install,
link, and use cloud-tasks. It ships with the CLI:

```sh
cloud-tasks skill install   # ~/.agents/skills/cloud-tasks, linked into ~/.claude/skills
cloud-tasks skill remove
```

A new release refreshes the installed copy automatically; only a copy cloud-tasks
wrote (marked `.managed-by-cloud-tasks`) is ever changed.

## Develop / remove

```sh
make test
make native-test
```

Tests use fake providers, temporary account config, and private Broadway/D-Bus
for native widgets; never the owner's accounts or desktop. Live-account behavior
still needs an owner-authorized integration pass. CLI requires only Python's
standard library; GTK/PyGObject are imported only when opening the app.

Remove a source install's `~/.local/bin/cloud-tasks`, its menu entry under
`~/.local/share/applications/`, and its app directory `~/.local/share/cloud-tasks`.
`~/.config/cloud-tasks` is kept unless you explicitly remove it. Provider tasks
and sign-ins remain unchanged.

MIT licensed.

## Replacing the legacy app

The legacy standalone app is retired. This product ships the extracted Rust
backend privately under its application directory, with protocol/fixture tests;
there is no subprocess dependency on the legacy CLI or its package. The shared
`icloud-session` service remains responsible for Apple sign-in.

Run `cloud-tasks migrate` to adopt an existing Apple cache without contacting
Apple or copying/moving files. The first native-app launch also adopts it.
Legacy cache paths are intentionally retained so account identity, sync tokens,
and existing records remain valid. Unlinking the account records that migration
is handled, so a later run does not silently relink it.

Arch packaging declares the legacy package replaced/conflicting. A source
installation is not a pacman transaction: after the new provider is built and
installed, remove the legacy package with the package manager. No provider data
or cache directories should be deleted during retirement.

Notification state stays in the existing Apple cache, preventing duplicate or
backlog alerts. Install/start the replacement timer for a source installation:

```sh
cloud-tasks migrate
systemctl --user disable --now icloud-reminders-background.timer
systemctl --user daemon-reload
systemctl --user enable --now cloud-tasks-background.timer
```

Skip disabling the old unit if it was never installed. The replacement unit
conflicts with the old timer/service, preventing both from running together;
notification clicks open Cloud Tasks. An Arch package installs/enables the new
user timer for subsequent logins. `cloud-tasks background` handles due Apple
reminders with the existing catch-up and once-per-due-time behavior. Google Tasks
still exposes dates only and has no timed notification service here.
