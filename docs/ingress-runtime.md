# Ingress-API en persistente queue

## Doel en migratiestatus

Sherlock zal fiches via HTTPS POST afleveren aan de ingress-API op bibib.
De Python-server luistert standaard alleen op `127.0.0.1:8000`. `ingress_tunnel.py` superviseert een afzonderlijke Cloudflare Quick Tunnel
voor externe HTTPS-bereikbaarheid. De component downloadt of installeert geen
binary en wijzigt geen services, router of firewall.

SQLite is de persistente transportqueue. GitHub is niet langer het gekozen
transportmechanisme voor Sherlock-fiches. Git blijft voor code, weekbranches,
worktrees, auditbare redactionele output en krantartefacten. Een weekworktree is
geen queue. Bestaande branches blijven behouden zolang de huidige runtime ze nodig heeft.

**Nu geïmplementeerd:** producer-API, queueopslag en Quick Tunnel/discoverypublisher.
**Volgende PR:** Ariadne consumeert rechtstreeks lokaal via de queue/database-interface.
Sherlock is nog niet omgezet en `daily` leest nog de bestaande Git-fiches en
manifesten. API-items blijven nu `pending`; POST betekent ontvangst, geen verwerking.
De API valideert alleen JSON-objecten, geen inhoudelijk fiche- of dagafsluitschema.
Het contract voor dagafsluiting en lege oogst wordt bij de consumentenstap uitgewerkt.

## Starten op bibib

Python 3.9.2 op Bullseye/armv7l volstaat; de ingressmodules hebben uitsluitend
standaardbibliotheekdependencies en hoeven geen tokenizer te importeren.
Zorg dat de bestaande map `/home/weekendkrant` beschrijfbaar is. De database is
`/home/weekendkrant/weekendkrant.sqlite3`, buiten Git. Bestaande audittabellen blijven intact.

Met `WEEKENDKRANT_INGRESS_TOKEN` reeds veilig geëxporteerd in de environment:

```bash
cd /home/weekendkrant/app
/home/weekendkrant/app/.venv/bin/python /home/weekendkrant/app/ingress_api.py
```

Een ontbrekend of leeg token stopt vóór het openen van SQLite. Er is geen
CLI-tokenoptie; neem geen token op in code, repository of commandlineargumenten.
Optionele argumenten zijn `--host`, `--port` en `--db`; standaard host is loopback,
poort 8000. Tests gebruiken altijd een tijdelijke database en loopback met poort 0.
De API heeft een eigen levensduur en gebruikt niet Ariadnes Git-`flock`;
SQLite beheert de korte databasetransacties.

## HTTP-contract

| Request | Resultaat |
| --- | --- |
| `GET /health` | Zonder authenticatie: `200`, JSON `status: ok` en aantal `pending` items; geen payloads of geheimen. |
| `POST /ingress` met `Authorization: Bearer <token>` | Geldig JSON-object: `201`, JSON met toegewezen `id`, na persistente commit. |
| Ontbrekende of verkeerde bearer-authenticatie | `401`, geen INSERT. Vergelijking via `hmac.compare_digest`. |
| Malformed JSON of top-level array/string/getal/boolean/null | `400`, geen INSERT. Ook NaN/Infinity worden geweigerd. |
| Ongeldige/ontbrekende/dubbele Content-Length of Transfer-Encoding | `400`; geen chunked requests. |
| Body groter dan 1 MiB | `413`. |
| SQLite niet beschikbaar tijdens een request | `503`, zonder interne foutdetails. |
| `GET /queue` of onbekend pad | `404`; er bestaat geen publieke queue-leesinterface. |

Stuur UTF-8 JSON met Content-Length, bij voorkeur `Content-Type: application/json`.
Requests krijgen een sockettimeout van 10 seconden. Deze kleine standaardbibliotheek-
server verwerkt requests sequentieel. Iedere herhaalde POST maakt een nieuw item;
er is geen deduplicatie, lease, retry of dead-lettermechanisme. Er is geen queue-
opruiming; bestaande Ariadne-auditretentie verwijdert geen pending items.

## Modulegrenzen en tests

- `ingress_queue.IngressQueue(db_path)`: schema aanmaken, `add(payload)` en `pending_count()`;
  elke operatie opent en sluit een eigen SQLite-connectie.
- `ingress_api.Config`: environmenttoken en configureerbare host/poort/database.
- `ingress_api.create_server(config)`: testbare HTTPServer; het CLI-entrypoint draait `serve_forever()`.

Vanuit de repositoryroot, met een venv:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_ingress*.py' -v
```

Geen test opent de echte runtime-database of een publieke netwerkverbinding.


## Quick Tunnel en vaste discoverypointer

De flow is:

`cloudflared Quick Tunnel -> actuele URL -> config/ingress-endpoint.json op GitHub -> MCP-plugin`

Weekendkrant Ingress leest uitsluitend deze vaste pointer:

```text
https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json
```

Het deterministische bestand bevat één regel UTF-8 JSON en een afsluitende newline:

```json
{"url":"https://example.trycloudflare.com/ingress"}
```

Dit bestand wordt pas bij de eerste geslaagde runtimepublicatie aangemaakt;
de PR bevat geen fictieve/live endpointpointer. GitHub is hier alleen service
discovery, geen transportqueue. De bearer-token staat uitsluitend in bibib/Sites
secretopslag. De tunnelcomponent heeft geen token nodig en verwijdert
`WEEKENDKRANT_INGRESS_TOKEN` uit de child-environment. Sherlock hoeft de URL niet
te kennen. Na iedere herstart/reboot ontstaat een nieuwe Quick Tunnel en wordt
de pointer automatisch vervangen. Raw GitHub kan kort cachen; de pointer is
geen garantie dat de tunnel nog leeft. Bij stoppen blijft de laatste pointer staan.

### Handmatig starten

Het gekozen productiepad voor de bestaande ARM32-binary is
`/home/weekendkrant/cloudflared`. Leg de reeds aanwezige binary daar handmatig
neer en zorg dat gebruiker `weekendkrant` haar kan uitvoeren; dit programma doet
geen download of upgrade. Een ander pad kan via `--cloudflared` of
`WEEKENDKRANT_CLOUDFLARED`. Gebruik voor Quick Tunnels geen bestaande
`~/.cloudflared/config.yaml` die de Quick Tunnel-aanroep beïnvloedt.
De API moet al draaien op `http://127.0.0.1:8000`.

```bash
/home/weekendkrant/app/.venv/bin/python /home/weekendkrant/app/ingress_tunnel.py --cloudflared /home/weekendkrant/cloudflared
```

De URL-timeout is standaard 60 seconden (`--url-timeout`). Stdout en stderr van
cloudflared worden samengevoegd en continu uitgelezen. De detector accepteert
uitsluitend HTTPS, één geldige DNS-label onder `trycloudflare.com` en optioneel
het pad `/ingress`. Credentials, poorten, query, fragment en andere paden/domeinen
worden geweigerd bij tunnelkandidaten. Gewone externe documentatie-/diagnostieklinks
worden genegeerd zonder whitelist; alleen URLs met `trycloudflare.com` in hun
authority worden als tunnelkandidaat strikt gevalideerd.
Herhaling van dezelfde URL is toegestaan; verschillende URLs stoppen veilig,
ook wanneer ze later verschijnen nadat de eerste al gepubliceerd is.
De component logt eigen status/fouten naar stderr voor journald en geeft geen
willekeurige child-output door. Geen eigen logrotatie.

SIGTERM/SIGINT beëindigen cloudflared netjes; na tien seconden volgt zo nodig kill.
Een onverwacht child-exit (ook code 0), URL-timeout of publicatiefout stopt de
component met exit 1. De child-exitcode staat in de foutmelding. Geen daemonizing.

### Git-publicatie zonder app/worktreewijzigingen

`publish_endpoint` maakt uitsluitend een tijdelijke zelfstandige shallow clone
van `main` via `git@github.com:willemg/weekendkrant.git`. Bestaande GitHub
SSH-authenticatie en vooraf vertrouwde hostkey moeten voor `weekendkrant` werken
zonder prompts. Geen nieuw GitHub-token. De publisher zet lokaal in die clone
de commitidentiteit `weekendkrant <weekendkrant@bibib>`.

Alle Git-opdrachten draaien in de tijdelijke map, nooit in `/home/weekendkrant/app`.
Ook geërfde `GIT_*` overrides worden verwijderd. De publisher registreert geen
extra worktree, gebruikt geen alternates/hardlinks naar de hoofdrepo en raakt
geen branches, index, bestanden of fetchrefs van app/weekworktree aan.
Alleen het discoverybestand wordt gestaged/gecommit, met message
`Werk ingress-endpoint bij`. Identieke bytes veroorzaken geen commit of push.
Push is uitsluitend `git push origin HEAD:refs/heads/main`.

Een gelijktijdige wijziging van remote `main` weigert de gewone push: geen force,
rebase of automatische merge. De service stopt duidelijk; een volgende start
neemt de nieuwste `main` als basis. SSH-/netwerkfouten stoppen eveneens.
Git-opdrachten hebben elk een timeout van 45 seconden. De gebruiker moet direct
naar `main` mogen schrijven; branchbescherming die dit verbiedt stopt veilig.

De tijdelijke clone wordt via `TemporaryDirectory` bij succes, fouten en normale
signalen opgeruimd. Handmatig starten gebruikt standaard `/tmp` (of `--temp-root`).
SIGKILL/stroomverlies kan geen Python-cleanup uitvoeren: gebruik daarom in productie
de onderstaande `RuntimeDirectory` onder `/run`. Systemd verwijdert die bij stoppen
of crash en reboot wist `/run`. Zo blijft ook na een harde crash geen permanente
repository-state achter. Er is geen extra permanente clone/worktree.

### Voorbeeld-unit: na merge handmatig installeren

Deze documentatie installeert niets in `/etc`. De ingress-API draait al via
`weekendkrant-ingress.service`. Voorbeeldbestand
`/etc/systemd/system/weekendkrant-ingress-tunnel.service`:

```ini
[Unit]
Description=Weekendkrant Quick Tunnel en discovery
Wants=network-online.target
After=network-online.target weekendkrant-ingress.service
Requires=weekendkrant-ingress.service

[Service]
Type=simple
User=weekendkrant
Group=weekendkrant
WorkingDirectory=/home/weekendkrant
RuntimeDirectory=weekendkrant-ingress-tunnel
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=no
ExecStart=/home/weekendkrant/app/.venv/bin/python /home/weekendkrant/app/ingress_tunnel.py --cloudflared /home/weekendkrant/cloudflared --temp-root /run/weekendkrant-ingress-tunnel
Restart=on-failure
RestartSec=30
KillMode=mixed
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`KillMode=mixed` geeft eerst het hoofdproces SIGTERM zodat het zijn child kan
beëindigen en de clone opruimen; systemd beëindigt na de stoptimeout alle resterende
processen. `RuntimeDirectoryPreserve=no` ruimt ook tussen herstarts op.
Na merge: code in app handmatig fast-forward bijwerken, bestaand binarypad en SSH
controleren, bovenstaande unit opslaan en dan handmatig:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now weekendkrant-ingress-tunnel.service
journalctl -u weekendkrant-ingress-tunnel.service -n 50 --no-pager
```

Controleer daarna de vaste raw discovery-URL. De echte MCP/POST-test en eventuele
pluginpublicatie gebeuren afzonderlijk; deze PR voert ze niet uit.

### Modulegrenzen en tests voor de tunnel

- `URLDetector`/`ingress_url`: strikte detectie en canonieke `/ingress`-URL.
- `supervise`: fake-testbaar child-output lezen, timeout, publicatiegrens en exits.
- `publish_endpoint`: deterministische JSON en geïsoleerde Git-publicatie.
- `main`/`stop_child`: configuratie, signalen en child-lifecycle.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_ingress_tunnel.py' -v
```

De tests gebruiken fake subprocess-output en tijdelijke lokale Git-remotes;
geen Cloudflare- of GitHub-call. De productiecode gebruikt alleen de Python
3.9-standaardbibliotheek en Git-opties die Git 2.30.2 ondersteunt.
