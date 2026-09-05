# Sharing BASSIGNANA EPC CONTROL with the whole company

This guide puts the application on one server that every employee reaches
from a browser, instead of one PC in the site office. Nothing in the
application changes between the two ways of running it; only environment
variables do.

## 1. What hosting means for this application

* It is a **server program with a database**. Every page is produced on the
  server from `data/bassignana.db`, and every form writes into it. That is why
  **GitHub Pages cannot host it**: GitHub Pages serves static files only and
  cannot run Python or keep a database.
* There must be **exactly one live database**. Once the hosted copy is in
  use, it is the project record; the copy on the office PC becomes a stale
  snapshot. Do not enter data in both.
* The host must have a **persistent disk**. Several "free" platforms
  (Render, Railway, Koyeb, Hugging Face Spaces, Vercel, Netlify) wipe the
  file system on every deploy or restart, which would throw the project
  record away. They are not suitable, whatever their pricing page says.
* The application contacts no external service, so the hosted copy needs no
  API key, no cloud database and no outbound internet.

## 2. Before going live: three settings

| Setting | Why |
|---|---|
| `BASSIGNANA_ACCESS_PASSWORD` | On a site LAN there is no login by design. On the internet there must be one: with this variable set, every page asks for the shared password once per device (remembered 30 days), photographs included. Wrong answers are slowed down and an address is locked out after 8 failures. |
| `BASSIGNANA_HTTPS=1` | Marks the session cookie *Secure*. Set it as soon as the site is reached over `https://`, which all three options below provide. |
| `BASSIGNANA_BEHIND_PROXY=1` | The platform or reverse proxy terminates HTTPS and forwards plain HTTP to the application; this makes it trust the forwarded scheme and address. |

Choose a long password (a sentence is fine) and share it in person or in the
company chat, not in a public place. Change it by changing the variable and
reloading; every device then has to sign in again.

## 3. Option A - PythonAnywhere (free, no card, persistent disk)

Best fit for this application: a free "Beginner" account runs one Flask web
app at `https://<username>.pythonanywhere.com` with HTTPS, a persistent 512 MB
disk and no credit card. The database, photographs and backups stay on that
disk across reloads. Limits that matter: one web app per account, a daily
CPU allowance (the site slows down rather than stopping if it is exceeded)
and an **expiry date that must be extended periodically** with one click on
the Web tab. The date is shown there and in the API; a reminder e-mail arrives
before it passes, and the site stops serving if it does. Check it after the
first deployment rather than assuming three months.

1. Create the account at <https://www.pythonanywhere.com> (Beginner plan).
   The username becomes the address, so choose something like
   `bassignana` or the company name.
2. **Consoles → Bash**, then paste these two lines and press Enter:

   ```bash
   curl -fsSL -o ~/bassignana_setup.sh https://raw.githubusercontent.com/bumincetin/bassig/main/deploy/pythonanywhere_setup.sh
   bash ~/bassignana_setup.sh
   ```

   This clones the repository into `~/bassignana`, creates a virtualenv and
   installs the requirements. It prints the remaining steps at the end.

   **If the repository is private**, the clone needs a credential. Create a
   fine-grained GitHub personal access token with read access to the
   repository, and run the second line as

   ```bash
   BASSIGNANA_REPO=https://<token>@github.com/bumincetin/bassig.git bash ~/bassignana_setup.sh
   ```

   The token is then stored in `~/bassignana/.git/config` on the server, so
   later `git pull` calls work without repeating it. Revoke it if the server
   is ever decommissioned.

   Download first and run second, rather than the shorter
   `bash <(curl ...)`: browser terminals often drop the leading word of a
   pasted line, and losing the `bash` there produces the confusing
   `/dev/fd/15: Permission denied`. This form fails safely instead, and lets
   you read the script with `cat ~/bassignana_setup.sh` before running it.
3. Everything from here can be done **for you by a script**, or by hand.

### 3a. The scripted way (recommended)

Go to **Account → API token** and press *Create a new API token*. Then, on
your own PC, in the project folder:

```
python deploy/pythonanywhere_deploy.py \
    --username YOURNAME \
    --token    THE_API_TOKEN \
    --password 'the shared password for the site' \
    --database data/bassignana.db
```

It creates the web app, writes the WSGI file with your password, sets the
source directory and virtualenv, adds exactly the three safe static mappings,
turns on Force HTTPS, uploads the current project record, reloads the site,
and finally checks `/healthz` and confirms that the dashboard redirects to the
login screen. Add `--dry-run` first if you want to see the steps without
changing anything, `--host eu` if you registered on eu.pythonanywhere.com, and
leave `--database` out to start with an empty record.

**`--python-version` must match the virtualenv.** The setup script prints the
right value, and `venv/pyvenv.cfg` on the server records it. A web app whose
Python differs from the virtualenv's cannot import the packages installed in
it, because compiled wheels are built for one version only. Two related traps:

* PythonAnywhere's API wants the version written `python313`, not `3.13`. The
  dotted form is refused with *"No such Python version: 3.13"*, which reads as
  though the interpreter were missing. The deployer accepts either spelling and
  sends the one the API wants.
* The versions offered for **web apps** are not the same set as the
  interpreters available in a **console**. If the version you need is refused,
  rebuild the virtualenv against one that is accepted:
  `cd ~/bassignana && rm -rf venv && python3.X -m venv venv && ./venv/bin/python -m pip install -r requirements.txt`.

**The database must not be in WAL mode.** PythonAnywhere stores files on a
network file system that cannot support it, and the journal mode is recorded
inside the database file, so converting it after the upload is too late.
Convert a copy before uploading:

```
python -c "import sqlite3; c=sqlite3.connect('copy.db'); print(c.execute('pragma journal_mode=DELETE').fetchone())"
```

It refuses to publish without a password, and refuses to upload over a
database that already exists on the server, so it is safe to re-run after an
update (`git pull` in a Bash console, then the same command without
`--database`).

### 3b. The manual way

3. **Web → Add a new web app → Manual configuration**, and pick the Python
   version the script reported (3.10 or newer).
4. On the Web tab fill in:
   * *Code*: Source code `/home/<username>/bassignana`, Working directory the
     same.
   * *Virtualenv*: `/home/<username>/bassignana/venv`.
   * *WSGI configuration file*: click the link, delete everything, paste the
     content of `deploy/pythonanywhere_wsgi.py`, and set `USERNAME` and
     `ACCESS_PASSWORD` at the top of it.
   * *Static files* (optional, makes CSS and JS faster). Map these three,
     and **only** these three - never `/static/` as a whole, or photographs
     would bypass the password:
     `/static/vendor/` → `/home/<username>/bassignana/static/vendor`,
     `/static/css/` → `.../static/css`, `/static/js/` → `.../static/js`.
   * *Security*: switch **Force HTTPS** on.
5. Press the green **Reload** button and open
   `https://<username>.pythonanywhere.com`. The login screen appears; the
   EN / TR / IT switch is on it too.
6. Move the current project record across (section 6), then Reload again.

### What cannot be automated, and why

The account itself has to be created by a person: signing up needs an e-mail
confirmation and a CAPTCHA. And the requirements have to be installed from a
Bash console in the browser once, because the PythonAnywhere API can create a
console but cannot start one - their documentation says "only connecting to
the console in a browser will do that". Those are steps 1 and 2 above;
everything after them is scripted.

**Updating later:** Consoles → Bash, `cd ~/bassignana && git pull`, then
Reload on the Web tab. Nothing under `data/`, `backups/` or
`static/uploads/` is in git, so an update never touches the live data.

## 4. Option B - Docker on a server you control

Any Linux machine with Docker works: a company server, a VPS, or an
always-free cloud VM (Oracle Cloud's Always Free tier offers a small VM with a
persistent disk; it asks for a card for identity verification but does not
charge). This option gives full control, a custom domain and no three-month
renewal.

```bash
git clone https://github.com/bumincetin/bassig.git bassignana
cd bassignana
cp .env.example .env            # set BASSIGNANA_ACCESS_PASSWORD, BASSIGNANA_HTTPS=1
docker compose up -d --build    # builds the image and starts it on port 8080
```

The named volume `bassignana-data` (mounted at `/data`) holds the database,
photographs, backups, source documents, secret key and logs. Rebuilding or
updating the container never touches it.

For HTTPS put Caddy in front (it obtains and renews the certificate itself):
`deploy/Caddyfile.example` is a complete two-line configuration. Then set
`BASSIGNANA_HTTPS=1` in `.env` and run `docker compose up -d` again.

**Updating later:** `git pull && docker compose up -d --build`.

**Without Docker:** `pip install -r requirements.txt`, set the variables, and
run `python run.py` under a process manager (systemd, or `waitress-serve`).
`wsgi.py` exposes `application` for gunicorn / uWSGI: use **one** worker
process with several threads, because the database is SQLite.

## 5. Option C - Keep it on the office PC, reach it from anywhere

If the PC in the site office stays on anyway, a Cloudflare Tunnel (free)
gives it a public HTTPS address without opening any port on the router, and
Cloudflare Access (free for up to 50 users) can restrict it to company e-mail
addresses in addition to the shared password.

1. Start the application as today (`START.bat`), with
   `BASSIGNANA_ACCESS_PASSWORD` set in the environment first.
2. Install `cloudflared` on the PC and, with a domain managed in your
   Cloudflare account, run once:

   ```
   cloudflared tunnel login
   cloudflared tunnel create bassignana
   cloudflared tunnel route dns bassignana bassignana.<your-domain>
   ```

   Create `%USERPROFILE%\.cloudflared\config.yml` with the tunnel id from the
   `create` step and one ingress rule to `http://localhost:5000`, then
   `cloudflared service install` so it starts with Windows.
3. Optional: in the Cloudflare Zero Trust dashboard add a self-hosted Access
   application for that hostname with a policy "e-mails ending in
   `@yourcompany`"; employees then sign in with a one-time code.

The trade-off is obvious: when the PC is off, the site is off.

## 6. Moving the current project record to the host

The repository deliberately contains **no live data**. The hosted copy starts
empty, so the current record has to be carried across once. Three things
make up the record:

| What | Where on the PC | Where on the host |
|---|---|---|
| Database | `data/bassignana.db` | PythonAnywhere: `~/bassignana/data/bassignana.db` (upload with the Files tab). Docker: `docker cp data/bassignana.db bassignana:/data/bassignana.db` |
| Photographs and evidence | `static/uploads/` | PythonAnywhere: `~/bassignana/static/uploads/`. Docker: `/data/uploads/` |
| Registered source-document files | `project_data/source_documents/` | PythonAnywhere: `~/bassignana/project_data/source_documents/`. Docker: `/data/source_documents/` |

Stop the local server (or take a backup from its Backup page and copy that
file instead of the live one), copy, then Reload / restart the host. Check
**Data Import / Export → history** and the Dashboard on the host: the
figures must match the PC. From that moment on, use only the host.

To go the other way - keep an offline copy - open **Backup** on the host,
press *Back up the database now* and download the file. Do that weekly; the
host's disk is the only place the record lives.

## 7. Environment variable reference

| Variable | Default | Meaning |
|---|---|---|
| `BASSIGNANA_ACCESS_PASSWORD` | empty (no login) | Shared password for the whole site |
| `BASSIGNANA_HTTPS` | `0` | `1` marks the session cookie Secure |
| `BASSIGNANA_BEHIND_PROXY` | `0` (`1` in the Docker image) | Trust `X-Forwarded-*` headers from the proxy in front |
| `BASSIGNANA_DATA_DIR` | `<repo>/data` | Database, logs, secret key, import workspace. When set, uploads, backups and source documents default to sub-folders of it |
| `BASSIGNANA_UPLOAD_DIR` | `<repo>/static/uploads` | Photographs and evidence |
| `BASSIGNANA_BACKUP_DIR` | `<repo>/backups` | Backups |
| `BASSIGNANA_SOURCE_DOC_DIR` | `<repo>/project_data/source_documents` | Registered document files |
| `BASSIGNANA_DATABASE_URI` | `sqlite:///<DATA_DIR>/bassignana.db` | Database location |
| `BASSIGNANA_SQLITE_JOURNAL_MODE` | `WAL` | `DELETE` on a network file system (PythonAnywhere) |
| `BASSIGNANA_PORT` / `PORT` | `5000` | Listening port; `PORT` is what most platforms inject |
| `BASSIGNANA_HOST` | `0.0.0.0` | Interface to bind |
| `BASSIGNANA_THREADS` | `8` | Waitress worker threads |
| `BASSIGNANA_SECRET_KEY` | generated once, kept in `DATA_DIR/secret_key` | Session signing key |

## 8. Platforms that were considered and why they were not chosen

| Platform | Problem for this application |
|---|---|
| GitHub Pages | Static files only; cannot run Python or hold a database |
| Render, Railway, Koyeb, Zeabur free tiers | File system is discarded on deploy / restart (or a card and a paid plan are needed for a disk) |
| Hugging Face Spaces | Free disk is not persistent |
| Vercel, Netlify, Cloudflare Workers | Serverless: no long-running Python process, no writable disk |
| Fly.io | Persistent volumes work well, but a card is required and the free allowance is not guaranteed for new accounts |

If the company later prefers a paid managed host, the Docker image in this
repository runs unchanged on any of them that offers a persistent volume.
