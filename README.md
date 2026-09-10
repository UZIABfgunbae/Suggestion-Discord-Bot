---
tags:
  - projekt/discord-bot
  - python
  - raspberry-pi
erstellt: 2026-09-10
status: einsatzbereit
---

# Discord Suggestion Bot

Member schlagen per `/suggest` Channels oder Rollen vor, das Admin-Team entscheidet per Button im Log-Channel. Persistenz über JSON in `data/`.

## Setup

### 1. Bot anlegen

1. [Developer Portal](https://discord.com/developers/applications) → **New Application** → Reiter **Bot**
2. **Reset Token** → Token kopieren
3. `cp .env.example .env` und Token bei `BOT_TOKEN=` eintragen

> [!warning] Token
> `.env` niemals committen oder teilen. Bei Leak sofort im Portal neu generieren.

### 2. Intents

Reiter **Bot** → *Privileged Gateway Intents* → **Server Members Intent** aktivieren (für die Rollenzuweisung nach Accept).

### 3. Bot einladen

`CLIENT_ID` = *Application ID* aus dem Reiter **General Information**:

```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=268520464
```

Enthaltene Rechte: View Channels, Send Messages, Embed Links, Read Message History, Manage Channels, Manage Roles.

> [!warning] Hierarchie & Sichtbarkeit
> - Die Bot-Rolle muss über allen Rollen stehen, die er vergeben soll. Neu erstellte Rollen landen ganz unten – das passt automatisch.
> - Der Bot muss jede Zielkategorie sehen und dort Channels verwalten dürfen, sonst schlägt Accept mit fehlenden Rechten fehl.

### 4. Installation

```bash
cd discord-bot
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Voraussetzung: Python ≥ 3.11, `discord.py` ≥ 2.6.

### 5. Starten

```bash
python main.py            # Commands werden nur bei Änderungen synchronisiert
python main.py --sync     # Sync erzwingen
```

Der Sync-Status liegt als Hash in `data/.command_hash`. Beim Start prüft der Bot Channels, Admin-Rolle und Rechte; Probleme gehen per DM an `owner_id` und ins Log.

### 6. Einrichten per Command

Auf dem Server als Mitglied mit **Administrator**-Berechtigung:

```
/setup-channels admin_role:@Admin-Team
```

Legt die Kategorie **Vorschläge** mit `#vorschlag-log` und `#vorschlag-audit` an (nur Admin-Rolle lesend + Bot), trägt alles in `config.json` ein und setzt dich als `owner_id`, falls noch leer. Mehrfach ausführbar: vorhandene Channels werden übernommen, nur fehlende neu angelegt. Kontrolle mit `/show-config`.

> [!important] Erster Start ohne `guild_id`
> Der erste Konfigurations-Command setzt `guild_id` automatisch. Danach **einmal neu starten**: Die Commands wandern vom globalen Sync (bis zu 1 h Verzögerung) auf den Server, globale Einträge werden entfernt.

> [!warning] Zugriffsschutz
> Jeder Konfigurations-Command trägt zwei kombinierte Absicherungen:
> 1. `@app_commands.default_permissions(administrator=True)` – im /-Menü für alle anderen unsichtbar.
> 2. `@app_commands.checks.has_permissions(administrator=True)` – harte Prüfung bei jedem Aufruf, auch wenn die Sichtbarkeit unter *Servereinstellungen → Integrationen* überschrieben wurde.
>
> Fehlt die Berechtigung, antwortet der globale Error-Handler (`main.py`) ephemer mit „Du brauchst Administrator-Rechte dafür.“ Auf einem fremden Server (andere `guild_id`) werden die Commands abgelehnt.

> [!info]- Alternativ: `config.json` von Hand
> IDs kopieren: Discord → *Einstellungen → Erweitert → Entwicklermodus*, dann Rechtsklick → **ID kopieren**. IDs dürfen als Zahl oder String stehen.
>
> | Key | Bedeutung | Command |
> |---|---|---|
> | `guild_id` | Server-ID | automatisch beim ersten Konfigurations-Command |
> | `log_channel_id` | Review-Embeds + Buttons | `/set-suggestion-channel` |
> | `audit_log_channel_id` | Audit-Zeilen | `/set-audit-log-channel` |
> | `admin_role_id` | Darf Buttons und `/suggestions list` nutzen | `/set-admin-role` |
> | `owner_id` | Startprobleme per DM, darf fremde Claims lösen | `/set-owner` |
> | `rate_limit_per_user` | Max. offene Vorschläge pro User (`0` = aus) | `/set-limits` |
> | `cooldown_after_reject_hours` | Sperre nach Ablehnung (`0` = aus) | `/set-limits` |
> | `auto_delete_after_days` | Entschiedene Vorschläge löschen nach X Tagen (`0` = aus) | `/set-limits` |
> | `allowed_categories` | Erlaubte Kategorien; leer = alle sichtbaren (Dropdown max. 25) | `/set-categories` |

## Befehle

| Befehl | Wer | Funktion |
|---|---|---|
| `/suggest` | alle | Ephemerer Ablauf: Typ → (Kategorie) → Modal |
| `/my-suggestions` | alle | Offene Vorschläge, ❌ Zurückziehen (nur `PENDING`), 📜 Verlauf |
| `/suggestions stats` | alle | Annahmequote, offene Vorschläge, Top 5 |
| `/suggestions list` | Admin-Rolle | Alle offenen Vorschläge mit Link zum Log-Embed |
| `/setup-channels` | Administrator | Kategorie + Log-/Audit-Channel anlegen und eintragen |
| `/set-suggestion-channel` · `/set-audit-log-channel` | Administrator | Vorhandenen Channel festlegen (prüft Bot-Rechte) |
| `/set-admin-role` · `/set-owner` | Administrator | Admin-Rolle bzw. Owner setzen |
| `/set-limits` | Administrator | Rate-Limit, Cooldown, Auto-Delete (ohne Werte: anzeigen) |
| `/set-categories` | Administrator | Erlaubte Kategorien hinzufügen/entfernen/leeren/anzeigen |
| `/show-config` | Administrator | Konfiguration + Prüfergebnis |

Buttons im Log-Channel: 🔍 Claim · 🔓 Unclaim · ✏️ Edit · 🟢 Accept · 🔴 Reject

## Betrieb auf dem Raspberry Pi 5

`/etc/systemd/system/suggestion-bot.service` (Pfad und User anpassen):

```ini
[Unit]
Description=Discord Suggestion Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/discord-bot
ExecStart=/home/pi/discord-bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now suggestion-bot
journalctl -u suggestion-bot -f      # Live-Log
```

## Daten

| Datei | Inhalt |
|---|---|
| `data/suggestions.json` | Alle aktuellen Vorschläge |
| `data/suggestions.json.bak` | Stand vor dem letzten Schreibvorgang; wird bei kaputter Hauptdatei automatisch geladen |
| `data/stats.json` (+ `.bak`) | Kumulierte Zahlen, überleben Auto-Delete |

Geschrieben wird atomar (`.tmp` → `os.replace`), ein Absturz hinterlässt keine halbe Datei.

## Abweichungen vom Build-Auftrag

> [!info]- Details (aufklappen)
> - **Persistente Buttons:** `DynamicItem` mit Regex-Template (`accept:a1b2c3` …), einmal in `setup_hook` registriert. Ersetzt das Laden je einer View pro offenem Vorschlag – gleiches Ergebnis, kein Start-Overhead.
> - **Startup-Checks** laufen in `on_ready`, weil der Guild-Cache vorher leer ist. Die Buttons sind trotzdem vor dem ersten Event registriert.
> - **`guild_id`** neu in `config.json` (Rechte-Checks + sofortiger Command-Sync).
> - **Unclaim:** Discord kann Buttons nicht pro User ausblenden – der Button ist sichtbar, wirkt aber nur für den Claimer. `owner_id` darf als Notausgang fremde Claims lösen.
> - **Verlauf** in `/my-suggestions` per Button statt „eingeklappt“ (gibt es in Discord nicht).
> - **Zurückziehen** entfernt den Eintrag; das Log-Embed wird grau markiert, Audit-Zeile wird geschrieben.
> - **Schema:** zusätzlich `log_channel_id`/`log_message_id` (Embed bleibt nach Wechsel des Log-Channels erreichbar) und `stats_counted` (verhindert Doppelzählung beim Auto-Delete).
> - **Locking:** `asyncio.Lock` (global + pro Vorschlag) statt OS-Filelock – der Bot ist ein einzelner Prozess.
> - **Konfigurations-Commands** sind Top-Level (`/set-…`) statt einer `/setup`-Gruppe, weil Discord `default_permissions` bei Subcommands ignoriert. `cogs/setup.py` verweigert den Start, wenn einem Command eine der beiden Absicherungen fehlt.
> - **Zusatzdateien:** `core/jsonio.py`, `utils/notify.py`, `views/my_suggestions_view.py`, `cogs/setup.py`.
> - Edits werden ebenfalls im Audit-Log protokolliert.
