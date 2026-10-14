# Weekendkrant Ingress: bronbeheer en deployment

Dit document is het canonieke contract voor bronbeheer, deployment en de
architecturale motivatie van de ChatGPT Site/MCP-plugin **Weekendkrant Ingress**.
Het beschrijft de werkwijze; het voert geen synchronisatie of publicatie uit.

## Eén bron voor ontwikkeling

Alle niet-geheime broncode van Weekendkrant wordt uitsluitend onderhouden in
`willemg/weekendkrant`. De canonieke pluginbron staat in
`plugin/weekendkrant_ingress/`.

ChatGPT Sites is geen ontwikkelrepository en geen alternatieve source of truth.
De interne bronopslag en versionering van Sites zijn uitsluitend onderdeel van
de deployment/runtimeomgeving. De Sites-bron is een projectie van één gekozen
GitHub-commit. Fixes of functionele wijzigingen mogen nooit rechtstreeks in
Sites ontwikkeld worden.

## Waarom de Sites-adapter nodig blijft

```mermaid
flowchart TD
    C["ChatGPT / Sherlock"] -->|MCP| S["Weekendkrant Ingress op ChatGPT Sites"]
    D["GitHub: config/ingress-endpoint.json"] -->|actuele endpoint-URL| S
    S -->|HTTPS + bearer token| T["Cloudflare Quick Tunnel"]
    T --> B["ingress_api.py op bibib"]
    B --> Q["SQLite"]
```

Bibib gebruikt bewust geen eigen publiek domein. De Cloudflare Quick Tunnel
levert een tijdelijke willekeurige hostname onder `*.trycloudflare.com`, die na
herstart kan veranderen. Daarom staat de actuele URL, met pad `/ingress`, in
`config/ingress-endpoint.json`. De Site/MCP-adapter leest deze discoverypointer
bij calls en leidt de backendpaden af op dezelfde gevalideerde host.

De Site biedt ChatGPT een stabiele MCP/pluginlaag terwijl de achterliggende
bibib-URL dynamisch mag blijven. GitHub verzorgt hier discovery en bronbeheer;
de requestdata gaat via de tunnel naar de API en SQLite.

De overwogen variant `ChatGPT -> rechtstreeks MCP op bibib` zou voor een
blijvende pluginregistratie een stabiele publiek bereikbare MCP-URL vereisen.
De huidige Quick Tunnel levert die stabiliteit niet. Een stabielere
Cloudflare-opstelling voor dit project zou extra DNS-/domeinbeheer vereisen.
Weekendkrant kiest expliciet om geen eigen domeinnaam of extra DNS-infrastructuur
te introduceren enkel voor deze plugin. De kleine Sites-adapter blijft daarom
voorlopig nuttig: dit is een bewuste trade-off.

## Twee afzonderlijke deploymentstappen

### Stap 1 — synchroniseren

Kies één concrete commit-SHA op `main` van `willemg/weekendkrant` waarvan de
pluginwijzigingen gereviewd, getest en gemerged zijn. Neem uitsluitend de bron
uit `plugin/weekendkrant_ingress/` van die commit en synchroniseer deze
ongewijzigd naar het bestaande ChatGPT Sites-project **Weekendkrant Ingress**.
Gebruik tijdens de synchronisatie die vaste commit, ook als `main` intussen
verder beweegt.

Tijdens synchronisatie wordt geen code geschreven, gerefactord of gefixt.
Handmatige afwijkingen en secretwijzigingen zijn niet toegestaan. De Sites-bron
moet een exacte projectie van de gekozen GitHub-bron zijn; Sites-versiegegevens
vervangen de GitHub commit-SHA niet.

### Stap 2 — publiceren

Publiceer vervolgens de gesynchroniseerde Site-versie. Pas publicatie maakt de
nieuwe MCP-toolversie actief voor ChatGPT. Synchroniseren verandert de bron in
de deploymentomgeving; publiceren activeert die versie. Het zijn twee
verschillende handelingen:

1. GitHub `main`, op één vastgelegde commit → synchronisatie → Sites-bron.
2. Die Sites-bron → publicatie → actieve Weekendkrant Ingress-plugin.

Voor dit project is momenteel geen directe GitHub→Sites deploymentintegratie
geconfigureerd/beschikbaar die `willemg/weekendkrant/plugin/weekendkrant_ingress/`
uit een gekozen commit rechtstreeks als deploymentbron gebruikt. Daarom bestaat
de expliciete synchronisatiestap. Dit beschrijft de projectinrichting, geen
algemene of blijvende beperking van het product.

Als ChatGPT Sites later een ondersteunde repo-backed deployment biedt waarbij
een specifieke GitHub-directory en commit rechtstreeks als deploymentbron
kunnen dienen, mag deze tweestapsflow worden vereenvoudigd. GitHub moet ook dan
de enige source of truth blijven.

Een Git-submodule lost dit op zichzelf niet op. De relevante eis is dat Sites
een specifieke GitHub-bron als build/deploymentsource ondersteunt, niet alleen
dat Sites Git-data kan zien. Zonder zo'n ondersteunde integratie vereist een
submodule nog steeds synchronisatie/versionering aan Sites-zijde en introduceert
zij bovendien een tweede Git-pointer. Deze werkwijze gebruikt geen submodule.

## Tests bij de bron; verificatie bij deployment

Functionele tests en de build horen bij de bron en draaien vóór merge vanuit de
GitHub-checkout:

```sh
npm --prefix plugin/weekendkrant_ingress test
npm --prefix plugin/weekendkrant_ingress run build
```

Na merge wordt de reeds geteste bron gedeployed. Sites is geen tweede
ontwikkelomgeving en er volgt daar geen tweede functionele testcyclus.
Deploymentverificatie mag uitsluitend controleren dat de juiste GitHub-commit
is gesynchroniseerd, de Site succesvol kan worden gepubliceerd en na publicatie
de verwachte toolversie daadwerkelijk bereikbaar is. Die laatste controle is
smoke verification van de deployment.

Als tijdens synchronisatie, publicatie of smoke verification een codeprobleem
blijkt, geldt steeds dezelfde route:

1. Stop de deployment; pas geen code aan in Sites.
2. Maak de wijziging in `willemg/weekendkrant` op een nieuwe branch.
3. Draai de functionele tests en build vanuit die checkout.
4. Laat de nieuwe GitHub-PR reviewen.
5. Merge de PR.
6. Deploy opnieuw vanaf de nieuwe concrete commit op `main`.

## Deploymentidentiteit

Iedere deployment moet herleidbaar zijn tot één concrete GitHub commit-SHA.
Het deploymentrapport vermeldt minimaal:

| Veld | Vast te leggen informatie |
| --- | --- |
| GitHub commit-SHA | Volledige SHA van de gekozen commit op `main`. |
| Sites-project | `Weekendkrant Ingress`. |
| Synchronisatie | Geslaagd of niet geslaagd voor die exacte bron. |
| Publicatie | Geslaagd of niet geslaagd voor de gesynchroniseerde versie. |
| Post-publish smoke verification | Eventuele controle, resultaat of expliciet niet uitgevoerd. |

Een geslaagde synchronisatie bewijst niet dat de versie actief is: het rapport
moet ook het publicatieresultaat bevatten. Leg waar beschikbaar de bijbehorende
Sites-versie/publicatie-identificatie vast om het verband te kunnen controleren.
Zo kan uit het laatste bevestigde publicatierapport worden afgeleid welke
GitHub-versie in productie draait. Dit is een rapportagecontract; er wordt geen
deploymentdatabase of automatische state geïntroduceerd.

Dit is het rapportagecontract voor nieuwe deployments, geen bewijs dat alle
identifiers historisch zijn vastgelegd. Voor de smoke van 14 oktober 2026 is
geen exact productie-SHA geregistreerd; de fase-2.5-gate steunt op de hieronder
beschreven complementaire systeemtest en bevestigde externe fichewrite.

## Runtimezaken buiten Git

`WEEKENDKRANT_INGRESS_TOKEN` blijft een runtime-secret. De repository bevat alleen
de secretnaam, nooit de echte waarde. De waarde wordt niet vanuit GitHub als
gewone broncode naar Sites gekopieerd en blijft buiten Git in de runtimeconfiguratie
van bibib en de secretopslag van Sites.

Deployment van broncode mag de bestaande secretconfiguratie niet overschrijven.
Sites beheert ook operationele versie-/deploymentrecords, pluginregistratie en
toegangsinstellingen. Operationele SQLite-data op bibib blijft buiten Git.
Niet-geheime bronrepresentaties, zoals het hostingmanifest met project-ID en
MCP-capability, horen wel bij de canonieke pluginbron.

## Operationele deployment smoke

Deze procedure vult de [lokale systeemtest en canonieke operationele
regel](daily-runtime.md#systeemtest-en-operationele-gate) aan. Voer haar uit wanneer
plugin/Sites, ingress-auth/configuratie, tunnel/discovery, systemd of productie-
ingress geraakt zijn. Na alleen een lokale runtimewijziging blijft controle van
de geïnstalleerde Ariadne-wrapper nodig; de materialisatieketen wordt bewezen
met de relevante geïsoleerde systeemtest.
Voer vóór deployment de lokale systeemtest uit op de gekozen broncommit.
Dit contract beschrijft controles, deze PR voert geen nieuwe productie-smoke uit.

De fase-2.5-gate steunt op twee complementaire bewijzen:

- De geïsoleerde lokale systeemtest bewijst ingress → SQLite → Ariadne →
  part/revision → processed.
- De echte deployment smoke bewijst de werkelijk gepubliceerde externe route →
  productie-ingress → persistente fichewrite.

Samen vormen zij de operationele gate. Een productie-item later door Ariadne
zien verwerken mag aanvullende observatie zijn, maar is geen verplichte
wachttijd om de deployment smoke groen te verklaren.

### 1. Veilige controles zonder redactionele writes

Leg de gekozen app-commit en, indien relevant, plugin-commit/Sites-publicatie vast
volgens het deploymentidentiteitscontract hierboven. Controleer op bibib:

```bash
systemctl is-active weekendkrant-ingress.service weekendkrant-ingress-tunnel.service
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health
cd /home/weekendkrant/app
./start_ariadne.sh telemetry
```

Verwacht actieve services, HTTP 200 met `status: ok` en een leesbaar telemetry-
rapport. Dit bewijst lokale service-/DB-bereikbaarheid en de geïnstalleerde
wrapper/interpreter, geen publieke route of succesvolle materialisatie.

Controleer vervolgens vanaf buiten bibib de actuele vaste discoverypointer en
het daarvan afgeleide publieke health-endpoint, zonder token:

```bash
python3 - <<'PY'
import json
import urllib.request
from urllib.parse import urlsplit
pointer = 'https://raw.githubusercontent.com/willemg/weekendkrant/main/config/ingress-endpoint.json'
with urllib.request.urlopen(pointer, timeout=10) as response:
    url = json.load(response)['url']
p = urlsplit(url)
assert (p.scheme == 'https' and p.hostname and p.hostname.endswith('.trycloudflare.com')
        and p.path == '/ingress' and not p.username and not p.password
        and p.port is None and not p.query and not p.fragment), 'Ongeldige discoverypointer'
with urllib.request.urlopen('https://' + p.hostname + '/health', timeout=10) as response:
    health = json.load(response)
assert health['status'] == 'ok', health
print(health)
PY
```

Dit bewijst discovery → publieke tunnel → ingress-health, nog geen bearer-auth of
Sites-route. Een actieve service alleen is onvoldoende: discovery kan verouderd
zijn terwijl de tunnel draait.

Roep daarna **via de werkelijk gepubliceerde ChatGPT/MCP-plugin** aan:

```json
filter_sherlock_sources({"urls": []})
```

Verwacht een geslaagd toolresultaat met `unreviewed: []`. Controleer rond hetzelfde
tijdstip in `journalctl -u weekendkrant-ingress.service --since '5 minutes ago'
--no-pager` de ontvangen en afgeronde `filter_sherlock_sources` met HTTP 200.
Dit bestaande filter schrijft geen runs, bronreviews of fiches, reserveert geen
URL en haalt geen bron op. Deze call bewijst ChatGPT → actieve Sites/plugin →
discovery/tunnel → geauthenticeerde backendcall. Doe dit niet via een lokale
HTTP-vervanger. Health alleen bewijst het auth-/pluginpad niet; deze read-only
call bewijst op zijn beurt nog niet de `/ingress`-schrijfroute of `run_id`-verwerking.

### 2. Laatste schrijfgrens: één legitieme fiche onder toezicht

Er bestaat geen dry-run-/deleteprotocol voor productie-ingress. Introduceer geen
synthetische testfiche, losse testrun of fictieve review in de redactionele queue.
Gebruik een eerstvolgende **echte, inhoudelijk gereviewde Sherlock-bron** tijdens
een begeleide run met de gedeployde canonieke instructies en plugin. Laat de
normale runstart/source-audit/publicatie/finish plaatsvinden; bewaar `run_id`,
topic en het bevestigde `queue_item_id` van één legitieme fiche.
Een onbekende POST-uitkomst mag niet blind opnieuw worden gepubliceerd: ingress
heeft geen deduplicatiesleutel. Onderzoek eerst logs/DB en meld onzekerheid.

Controleer de persistente queue-/runkoppeling read-only op bibib, met het echte
ID als argument in plaats van `123`. Zowel pending als processed is toegestaan:
het bewijs betreft de bevestigde productie-write, niet het consumptiemoment.

```bash
.venv/bin/python - 123 <<'PY'
from contextlib import closing
import json
import sqlite3
import sys
identity = int(sys.argv[1])
with closing(sqlite3.connect('file:/home/weekendkrant/weekendkrant.sqlite3?mode=ro', uri=True)) as db:
    row = db.execute('''SELECT q.id,q.status,q.payload,f.run_id,r.topic
        FROM ingress_queue q
        JOIN sherlock_fiches f ON f.queue_item_id=q.id
        JOIN sherlock_runs r ON r.id=f.run_id WHERE q.id=?''', (identity,)).fetchone()
assert row is not None, 'Persistente fichewrite of runkoppeling ontbreekt'
queue_id, status, raw, run_id, topic = row
payload = json.loads(raw)
assert payload['topic'] == topic, 'Topicmatch ontbreekt'
assert isinstance(payload['content'], str) and payload['content'].strip(), 'Fichecontent ontbreekt'
print(dict(queue_item_id=queue_id, run_id=run_id, topic=topic, status=status))
PY
```

Een succesvolle check, samen met de echte pluginpublicatie en bijbehorende
backend-audit, bewijst de externe schrijfroute tot de persistente fichewrite.
De fiche is normale gewenste redactionele state; er is niets op te ruimen.
Verwijder of reset nooit handmatig queue-, audit- of provenancegegevens om een
smoke groen te maken. Als geen geschikte echte bron beschikbaar is, noteer de
schrijfgrens expliciet als **niet uitgevoerd** en laat de operationele gate open.
De veilige controles uit stap 1 kunnen wel al groen zijn.

### 3. Aanvullende observatie: latere productie-materialisatie

Deze controle is optioneel en bepaalt niet of de deployment smoke groen is.
Laat de normale kwartierconsument verwerken; er hoeft geen handmatige Ariadne-run
te worden gestart en er hoeft niet op een bezet slot te worden gewacht om de
smoke af te sluiten. Wie de latere verwerking wil observeren, kan na de normale
consumptie onderstaande read-only controle uitvoeren:

```bash
.venv/bin/python - 123 <<'PY'
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import sys
identity = int(sys.argv[1])
with closing(sqlite3.connect('file:/home/weekendkrant/weekendkrant.sqlite3?mode=ro', uri=True)) as db:
    rows = db.execute('''SELECT q.status,f.run_id,a.content,a.sha256,p.week,p.topic,p.part,
        r.revision,r.path,r.sha256,m.materialized_at
        FROM ingress_queue q
        JOIN sherlock_fiches f ON f.queue_item_id=q.id
        JOIN source_archive a ON a.queue_id=q.id
        JOIN revision_sources s ON s.queue_id=q.id
        JOIN parts p ON p.id=s.part_id AND p.active_revision=s.revision
        JOIN part_revisions r ON r.part_id=p.id AND r.revision=s.revision
        JOIN source_materializations m ON m.queue_id=q.id WHERE q.id=?''', (identity,)).fetchall()
assert len(rows) == 1, 'Nog niet verwerkt of provenance ontbreekt; controleer logs/telemetry'
status, run, content, source_sha, week, topic, part, revision, path, sha, at = rows[0]
assert status == 'processed', status
data = Path(path).read_bytes()
assert hashlib.sha256(content).hexdigest() == source_sha
assert hashlib.sha256(data).hexdigest() == sha
assert data.count(content) == 1
assert data.count(('--- SOURCE queue:%d date=' % identity).encode()) == 1
print(dict(queue_item_id=identity, run_id=run, week=week, topic=topic,
           part=part, revision=revision, materialized_at=at, status=status))
PY
```

Een succesvolle aanvullende check bevestigt productie-materialisatie met coherente
bron-/revisieprovenance. Een nog pending item maakt een reeds bevestigde
persistente fichewrite niet ongeldig en houdt de deployment smoke niet open.

### 4. Bewijs vastleggen vóór onbeheerde runs

Rapporteer de lokale systeemtest, tijdstip en uitkomst, service/health-resultaten,
read-only pluginresultaat met corresponderende backend-audit en de echte
run-/queue-identiteit met bevestigde persistente fichewrite. Leg app/plugin-commit
en Sites-publicatie vast wanneer beschikbaar volgens het deploymentcontract;
ontbrekende historische identifiers blijven expliciet onbekend, geen geraden SHA.
Een processed part/revision-controle mag als aanvullende observatie worden
opgenomen en is geen vereiste voor de gate. Noem iedere niet uitgevoerde
verplichte grens expliciet. Een geslaagde lokale call of alleen groene
unit-/integratietests mag geen volledig geslaagde deployment-smokeclaim opleveren.
Bij fouten: deployment stoppen/onderzoeken via de bestaande bronbeheerroute;
geen nachtelijke/onbeheerde werking als operationeel bewezen vrijgeven zolang
de relevante verplichte grens onbewezen is. Fase 2.5 blijft dan open vóór fase 3.

Het geregistreerde operatorbewijs van 14 oktober 2026 is: 192 tests groen op bibib
en een echte Sherlock-run via de herstartte productie-ingress, met succesvolle
runstart, source-audit, fichepublicaties en runfinish. Samen dekken de lokale
systeemtest en deze deployment smoke de fase-2.5-gate. Een exact productie-SHA of
handmatig geverifieerd processed/revision-ID is hierbij niet geregistreerd.
