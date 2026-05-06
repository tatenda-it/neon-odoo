# Neon Odoo 17 — Local Docker Stack

Phase 1 CRM development environment for Neon Events Elements.
Runs Odoo 17 Community + PostgreSQL 15 in Docker, accessible at
**http://localhost:8069**.

---

## 1. Prerequisites

- Docker Desktop (Windows / macOS) **or** Docker Engine + Docker Compose plugin (Linux)
- Port `8069` and `8072` free on the host machine
- ~2 GB free disk space for images and volumes

Verify Docker is installed:

```bash
docker --version
docker compose version
```

---

## 2. Project Layout

```
neon-odoo/
├── docker-compose.yml      # Service definitions (Odoo + Postgres)
├── config/
│   └── odoo.conf           # Odoo server configuration
├── addons/                 # Drop custom modules here
│   └── README.txt
├── .gitignore
└── README.md               # This file
```

---

## 3. Start the Stack

### 3.1 Bootstrap a fresh clone

Two pieces of state are deliberately not committed to git and must be set up once after cloning:

**Initialise OCA submodules.** The `oca/queue`, `oca/server-tools`, and `oca/web` directories are git submodules that ship the `queue_job`, `auditlog`, and `web_responsive` modules respectively. Without them, the database will boot but those modules log `not installable, skipped` and the responsive grid layout / theme switcher disappear.

```bash
git submodule update --init --recursive
```

**Create the Odoo config from the template.** `config/odoo.conf` is gitignored because it carries the master and Postgres passwords. Copy the example and fill in real values:

```bash
cp config/odoo.conf.example config/odoo.conf
```

Then edit `config/odoo.conf`:

- `admin_passwd` — strong master password before exposing Odoo to anyone outside localhost.
- `db_password` — must match `POSTGRES_PASSWORD` in `docker-compose.yml` (default `odoo`).

Without this file the container falls back to Odoo defaults and the `/mnt/extra-addons` addons path is **not** loaded — no custom or OCA modules will be visible.

> **Note for existing developers:** if you ever need to apply host changes to a long-running Odoo container (new module dropped under `addons/`, freshly initialised submodule, edited conf), use `docker compose up -d --force-recreate odoo`. Plain `restart` does not refresh bind mounts on Docker Desktop for Windows.

### 3.2 Bring up the stack

From inside the `neon-odoo/` directory:

```bash
docker compose up -d
```

First run downloads the `odoo:17` and `postgres:15` images (~600 MB total) and initialises the database — allow 1–2 minutes.

Check that both containers are healthy:

```bash
docker compose ps
```

Expected output shows `neon-odoo-app` and `neon-odoo-db` both in state `running`.

Tail the Odoo logs if anything looks off:

```bash
docker compose logs -f odoo
```

---

## 4. First-Time Database Setup

1. Open **http://localhost:8069** in a browser.
2. The Odoo database manager appears on first launch. Fill in:
   - **Master Password:** `neon_admin_change_me` (matches `config/odoo.conf` — change it there before going live)
   - **Database Name:** `neon_crm`
   - **Email:** Munashe's or Robin's login email
   - **Password:** strong password for the admin user
   - **Language:** English (UK)
   - **Country:** Zimbabwe
   - **Demo data:** leave **unchecked** for a clean production-like build
3. Click **Create database**. Odoo initialises in ~30 seconds and drops you into the dashboard.

---

## 5. Install the CRM Module

1. Activate **Developer Mode**: Settings → scroll to bottom → *Activate the developer mode*.
2. Go to **Apps**, clear the default "Apps" filter, and search for **CRM**.
3. Install **CRM** (technical name `crm`).
4. Also install, as they support the Phase 1 brief:
   - **Contacts** (`contacts`) — usually installed automatically
   - **Calendar** (`calendar`) — for follow-up scheduling
   - **Discuss** (`mail`) — for internal notifications
   - **WhatsApp** integration module (Odoo 17 Enterprise) — skip on Community; use a third-party connector or webhook instead

---

## 6. Common Commands

| Action | Command |
|---|---|
| Start stack | `docker compose up -d` |
| Stop stack | `docker compose down` |
| Stop + wipe all data (destructive) | `docker compose down -v` |
| Restart Odoo only | `docker compose restart odoo` |
| Update module list after dropping a new addon | `docker compose restart odoo` then *Apps → Update Apps List* in UI |
| Shell inside Odoo container | `docker compose exec odoo bash` |
| Postgres shell | `docker compose exec db psql -U odoo postgres` |
| Backup the database | Use the Odoo database manager at `/web/database/manager` |

---

## 7. Security Checklist Before Anyone Else Uses This

- [ ] Change `admin_passwd` in `config/odoo.conf` from `neon_admin_change_me` to a strong secret.
- [ ] Change the Postgres password in `docker-compose.yml` (both the `db` service env and the `odoo` service env must match).
- [ ] Set `list_db = False` in `odoo.conf` once the `neon_crm` database is created.
- [ ] If exposing beyond localhost, put Odoo behind Nginx/Traefik with HTTPS and set `proxy_mode = True`.
- [ ] Schedule regular backups of the `odoo-db-data` Docker volume.

---

## 8. Troubleshooting

**Port 8069 already in use**
Another service is bound to 8069. Either stop it, or change the left-hand port in `docker-compose.yml`, e.g. `"8070:8069"`, then use `http://localhost:8070`.

**"Database connection failure"**
The `db` container hasn't finished initialising. Wait 15 seconds and reload. If it persists, run `docker compose logs db`.

**Custom module not appearing in Apps**
Restart the Odoo container (`docker compose restart odoo`), then in the UI: Apps → *Update Apps List*. Confirm the module folder contains a valid `__manifest__.py`.

**Want to start over from scratch**
`docker compose down -v` wipes both data volumes. The next `docker compose up -d` gives you a fresh Odoo with no databases.

---

## 9. Next Steps (aligns with Phase 1 Brief §7)

- Week 1–2: Configure CRM pipeline stages to match the brief (New Enquiry → Confirmed/Lost).
- Week 2–3: Build WhatsApp Business API webhook → Odoo lead creation.
- Week 3–4: Connect Meta Lead Ads webhook and the website enquiry form.
- Week 5: Build the eight automated actions listed in §5 of the brief.
- Week 6: Train Munashe and Lisar; go live.
