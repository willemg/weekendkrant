# Deterministische backlogverwerking op bibib

`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`

## Selectiecontract

MCP/SQLite is de persistente ingressqueue. Een `daily`-run bepaalt datum D
expliciet in `Europe/Brussels` en materialiseert één deterministische snapshot.
Alle geldige pending fiches met `payload.date <= D` zijn verwerkbaar. Geldige
fiches met `payload.date > D` blijven pending. De payloaddatum is provenance
en ordening, geen eenmalig consumptievenster.

Een tijdelijke fout laat de geselecteerde items pending. De volgende geschikte
run ziet ze vanzelf opnieuw, samen met nieuw werk. Geen catch-upmodus,
dagheropening, retriescheduler, manifest of polling is nodig. Maandagfiches die
maandag faalden kunnen dinsdag samen met dinsdagfiches verwerkt worden.

Het schema-version-1-contract blijft exact:

```json
{"schema_version": 1, "topic": 2, "date": "2026-10-05", "content": "# Bronfiche\n..."}
```

Exact deze vier keys, integer schema_version 1, integer topic 1, 2 of 3,
canonieke geldige `YYYY-MM-DD` en niet-lege Markdowntekst. Booleans gelden niet
als integers. Alle pending records worden strikt gevalideerd, ook toekomstige.
Malformed JSON, dubbele keys, NaN/Infinity en onbetrouwbare datums falen zichtbaar;
ze worden nooit stil overgeslagen en blijven pending.

## Lege queue en legacy-dagaudit

Geen verwerkbare items geeft JSON `success` met `threads: 0`, zonder files te
herschrijven, items te consumeren of een fictieve afgesloten dag te registreren.
Een later ontvangen fiche voor dezelfde datum blijft gewoon verwerkbaar.

`days`, `threads` en `sources` blijven historische legacyprovenance. Nieuwe
partverwerking schrijft daar niets meer in. `attempts` bewaart alleen nog
zichtbare runtimefouten met uitvoerdatum; het is geen partauditmodel.
Geen dagstatus of ontbrekend dagrecord bestuurt de queue.

## Week/topic-parts en immutable revisies

De stabiele partidentiteit is `(ISO-weekjaar/week, topic, partnummer)`.
Nieuwe bronnen binnen een week/topic volgen `(payload.date, numerieke queue-ID)`.
Bestaande bronnen blijven altijd eerst in hun geregistreerde volgorde staan;
een late oudere datum herschikt dus niets. Fiches blijven ondeelbaar.

Er is maximaal één open part per week/topic. Past de volgende fiche niet,
dan sluit de huidige part definitief en begint de volgende. Geen bin-packing
of heropening. De volgende run vult alleen de nog open part. Een weekwissel
maakt een andere identiteit; een oude week kan nog late fiches ontvangen in
haar open part. Backlog van meerdere weken kan in één snapshot worden verwerkt.

Outputlayout:

```text
/home/weekendkrant/draden/2026_W41/topic_2/part_0001/rev_0001.txt
/home/weekendkrant/draden/2026_W41/topic_2/part_0001/rev_0002.txt
```

De nieuwe header is `WEEKENDKRANT-PART-1`, met week, topic, part, revision,
tokenizer en reserved_tokens. Een part heeft geen eigen `date:`. Iedere
source-afscheiding bevat `queue:<id>`, oorspronkelijke datum, content-SHA-256
en bytegrootte. De exacte UTF-8 fichebytes worden zonder normalisatie bewaard.

`tiktoken==0.12.0` / `cl100k_base` meet de volledige serialization inclusief
header en source-metadata. Maximaal 35.000 inputtokens waarvan 5.000 reserve:
de bronpart gebruikt maximaal 30.000 tokens. Eén onmogelijke fiche faalt de
volledige snapshot zichtbaar; niets wordt afgekapt of processed gemarkeerd.

Elke groei maakt een nieuwe revisie. Revision 1 blijft byte-for-byte behouden,
met dezelfde hash, tokenmeting, bronposities en bronvolgorde. De actieve pointer
verschuift pas bij succesvolle DB-commit. JSON behoudt het veld `threads` voor
compatibiliteit; dit telt nu de nieuw geregistreerde partrevisies in deze run.

## Migratie en bewuste cut-over

De runtime gebruikt de centrale `database.migrate()` via `daily.database()` en
`IngressQueue`. `database.py` en de genummerde migraties in `migrations/` beheren
het volledige SQLite-schema voor zowel nieuwe als bestaande databases.
`parts.py`, `daily.py` en `ingress_queue.py` beheren geen eigen DDL.
De actuele schemaversie en migratiedetails staan uitsluitend in
[databasebeheer](database.md). Zie daarnaast het
[partmodel en provenancecontract](audit-trail.md#partmodel-en-provenance).

Bestaande parts, revisies en bronmemberships blijven exact behouden. Heropenen
is idempotent; onbekende nieuwere versies worden geweigerd.

Bestaande `ingress_queue`, `days`, `attempts`, `threads` en `sources` blijven
intact. `YYYY-MM-DD_PPPP.txt` en hun provenance worden niet geconverteerd of
geherinterpreteerd. Nieuwe succesvol verwerkte items gaan uitsluitend naar het
partmodel, dat zonder nieuwe-style part bij part 1/revision 1 begint.
Geen retentie, DELETE, Git-cleanup of VACUUM hoort bij deze migratie.

## Transactie en crashgedrag

De niet-blokkerende lokale `flock` op `/home/weekendkrant/ariadne.lock` beschermt
één Ariadne-consument. Het lockpad is in tests injecteerbaar en staat buiten de
applicatierepository. Er zijn geen Git-commando's, branchcontroles of
weekworktree-operaties nodig voor `daily`; ook een gewone applicatiemap volstaat.
DB, output en lock mogen niet in de applicatierepository staan.

Selectie en payloadvalidatie houden geen SQLite write-transactie open. Een korte
read-transactie leest coherente partstaat en actieve bronmembership; die eindigt
vóór planning, tokenisatie en filewrites. De producer kan tijdens die bewerkingen
via een andere connection invoegen. Na de snapshot toegevoegde IDs vallen buiten
de run. Alleen de oorspronkelijke snapshot wordt verwerkt.

Nieuwe files worden via tempfile, file-fsync, atomische hard-link-publicatie en
directory-fsync geschreven. Een identieke orphan wordt hergebruikt. Een gewijzigde
snapshot mag andere bytes op een nog ongeregistreerd pad atomisch vervangen;
geregistreerde revisiepaden worden vooraf geweigerd. Alle consumenten moeten
hetzelfde runtime-slot gebruiken. Geen bestaande succesvolle file wordt vervangen.

Pas daarna start een korte `BEGIN IMMEDIATE`. Binnen die transactie worden alle
snapshot-IDs opnieuw op pending gecontroleerd én alle betrokken week/topic-
partstaten vergeleken met de geplande snapshot. Gewijzigde actieve revisies,
open/closed-staat of partinventaris worden geweigerd. Bronarchief, nieuwe parts,
revisies, memberships, sluiting, actieve pointers en exact de snapshot-IDs als
processed worden samen gecommit.

Bij file-, registratie-, pointer- of commitfout blijven eigen queue-items pending
en de oude actieve revisies intact. De DB-provenance van de hele snapshot is
all-or-nothing. Eerder geregistreerde revisies worden nooit gewijzigd.
Ongeregistreerde files mogen als orphan achterblijven; zij zijn geen actieve
of gepubliceerde provenance. Retry van dezelfde snapshot en geregistreerde
DB-staat geeft dezelfde geplande revision/path/bytes.

De fout wordt gelogd en de CLI stopt niet-nul. Bij een onbeschrijfbare DB kan ook
de foutregistratie mislukken; logging blijft zichtbaar. Bewaar database en
succesvolle revisiebestanden samen. Verwijderde succesvolle files worden niet
automatisch gereconstrueerd.

## Materialisatietijdprovenance vanaf schema 6

Een niet-lege succesvolle snapshot registreert per nieuw queue-item een immutable
`source_materializations`-record met UTC-tijdstip. Het tijdstip wordt geobserveerd
na partregistratie en statusupdates, vlak vóór de finale commit. Het is een
registratiemoment, geen meting van het exacte fsync-/commitmoment of de looptijd.
De klok is de actuele UTC-hostklok, onafhankelijk van fichepayloaddatum en de
`now`-parameter voor Belgische selectiedatum. Alle items van één snapshot krijgen
hetzelfde tijdstip. De records worden samen met bronarchief, revisies en processed-
status gecommit; iedere fout draait alles terug. Een lege run maakt geen record.
Retry na rollback registreert het nieuwe werkelijke registratiemoment; een reeds
processed item wordt niet opnieuw geteld. Oude items krijgen geen geraden tijd.
Zie [materialisatiegroei in telemetry](telemetry.md#materialisatiegroei).

## Expliciete lokale offer/seal-operatie

`PartStore(db).offer(part_id, revision)` verwacht een concrete part-ID en exact
zijn geregistreerde actieve revisie. De connection mag geen actieve transactie
hebben: de operatie beheert zelf een korte `BEGIN IMMEDIATE`, commit en rollback.
Ze retourneert een immutable `PartOffer(id, part_id, revision, created_at)`.
Een identieke retry retourneert hetzelfde record met dezelfde ID en UTC-tijd.
Een oude, fictieve of niet-actieve revisie wordt geweigerd.

SQLite valideert de offerinsert en sluit de part in dezelfde statement via een
trigger. Bij insert-, seal- of commitfout wordt de hele operatie teruggedraaid.
Ook een reeds door overflow gesloten part met een actieve revisie is offerbaar.
Een offer schrijft, kopieert of rendert geen revisiebestand. Hash, tokenmeting en
membership blijven de bestaande geregistreerde provenance.

Open parts mogen groeien via nieuwe revisies. Gesloten parts mogen geen bronnen
meer krijgen. Sealed/offered betekent gesloten plus één lokaal persistent offer
voor de exacte actieve revisie; het bewijst geen verzending of ontvangst door
Leonardo. Na sealing maakt normale `daily` de volgende part wanneer geen andere
part open is. Er is geen automatische selectie, scheduler of modelcall.

## Nog niet geïmplementeerd

Daadwerkelijke Leonardo-calls, rolling dossierstate, dossiers,
Kuifje-missies, callbudgetten, aanbiedplanning en eindredactionele
weekdeadline volgen later. Een overflow sluit alleen bronaanvulling; er gebeurt
geen automatische aanbieding. Deze stap voegt geen cronjob toe.

## Installeren en handmatig controleren op bibib

Python 3.9.2 blijft ondersteund. Vanuit `/home/weekendkrant/app`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start_tests.sh
./start_ariadne.sh daily
```

De wrappers gebruiken rechtstreeks `/home/weekendkrant/app/.venv/bin/python` en
stellen `TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken` in. De eerste
bundelmeting kan de encodingcache vullen; hergebruik die cache voor cron.
Tests gebruiken uitsluitend tijdelijke databases, outputmappen en locks.
Ze openen geen productie-DB. Het JSON-resultaat verschijnt op stdout;
runtimelogging staat in `/home/weekendkrant/logs/ariadne.log` met 1 MiB rotatie en
vier backups. Controleer de JSON-uitkomst, logging en lokale provenance bij een
handmatige productierun; verander geen status om een dag opnieuw te openen.

## Croncontract na merge

`daily` blijft de commandonaam; de selectiedatum sluit verdere runs op dezelfde
dag niet uit. De voorlopige lokale cadence is iedere **15 minuten**, op :00,
:15, :30 en :45. Dit onafhankelijke cadence-deel van fase 6 wordt vervroegd
ingevoerd; het vereist geen generieke jobs of intelligente orchestratie.
De PR wijzigt de productiecrontab niet. Na merge en applicatie-update moet de
beheerder de crontab van gebruiker `weekendkrant` op bibib handmatig aanpassen.

Verwijder **handmatig** de obsolete zondagregel uit de crontab op bibib:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

Vervang de oude regel `0 10 * * * ... start_ariadne.sh daily ...` door exact
deze voorlopige regel, met de hosttijdzone `Europe/Brussels`:

```cron
*/15 * * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
```

`daily` is de enige huidige operationele Ariadne-taak. `prepare-week` bestaat niet
meer in de CLI. De code wijzigt geen crontab, verwijdert geen historische branches
of worktrees en installeert geen nieuwe zondagjob.

Controleer met `crontab -l` dat precies één `daily`-regel bestaat en de oude
dagelijkse regel weg is. Controleer na een volgend kwartier de logfile
`/home/weekendkrant/logs/ariadne.log` en `./start_ariadne.sh telemetry` voor
nieuwe bevestigde materialisaties, of een expliciete lege run. Herhaald starten
maakt geen dubbele archiefbron of materialisatietijdregistratie; lege runs
schrijven geen revisies. Een proces dat het bestaande `flock` niet krijgt stopt
direct niet-nul met een diagnose, zonder queue/provenance aan te raken. Het wacht
niet op de vorige run. Later ontvangen of na een fout pending gebleven fiches
worden in een volgende vrije run verwerkt. De bestaande snapshot-, korte
transactie-, orphan/retry- en crashsafe regels blijven ongewijzigd.

15 minuten is een voorlopige keuze, geen gemeten optimum of gegarandeerde
verwerkingslatency. Bij langere runs kunnen kwartierstarts worden geweigerd;
pas later op basis van logging en echte materialisatietijden de cadence aan.
Rollback van alleen het ritme: vervang de kwartierregel handmatig door
`0 10 * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null`.
Verwijder of reset daarvoor geen queue-items, parts of provenance.

## Bewaarbeleid

De automatische achtwekenretentie, `prune_history()`, `week_report()` en `VACUUM`
zijn verwijderd. Startup/migratie verwijdert geen bestaande SQLite-rijen.
Alle bestaande data blijft behouden; er is voorlopig geen automatische opruiming.
Een toekomstig beleid wordt apart ontworpen rond bronarchief, partrevisies,
Leonardo-state, actieve dossiers, missies en callaudit.

## Systeemtest en operationele gate

**Projectregel:** na een wijziging die een bestaande end-to-end-flow kan raken,
zijn groene gewone tests onvoldoende. De wijziging is pas operationeel bewezen
na een groene relevante geautomatiseerde systeemtest en, als deploymentgrenzen
zijn geraakt, een geslaagde relevante deployment smoke. Dit geldt na grote
wijzigingen aan runtime, ingress, plugin, database of orchestratie, in het
bijzonder vóór nachtelijke/onbeheerde Sherlock-runs. Leg commit, opdracht,
tijdstip, uitkomst en eventuele nog onbewezen grenzen vast in PR/deploymentrapport.
Deze discipline is de [fase-2.5-gate vóór fase 3](intelligent-worker-orchestration.md#fase-25---systeemtest-en-operationele-smoke-test).

| Niveau | Bewijs en grens |
| --- | --- |
| Unit | Eén functie/regel, eventueel met mocks, bijvoorbeeld fichevalidatie of planning. |
| Integratie | Samenwerking tussen modules en echte opslag/HTTP, vaak in hetzelfde testproces, bijvoorbeeld `run_daily` met een tijdelijke DB. |
| Systeem | Bestaande runtime via echte proces-, HTTP-, SQLite- en bestandgrenzen, zonder interne functies achter elkaar aan te roepen. |
| Deployment smoke | Operationele controle van de werkelijk geïnstalleerde/gepubliceerde componenten en hun configuratie. Aanvullend op lokale systeemtests. |

De fase-2.5-gate combineert twee complementaire bewijzen: de geïsoleerde lokale
systeemtest bewijst ingress → SQLite → Ariadne → part/revision → processed;
de echte deployment smoke bewijst de werkelijk gepubliceerde externe route →
productie-ingress → persistente fichewrite. Samen maken zij de gate operationeel
groen. Latere verwerking van dat productie-item door Ariadne is aanvullende
observatie, geen verplichte wachttijd om de deployment smoke groen te verklaren.

### Opdracht en eenmalige voorbereiding

Vanuit de repositoryroot, met geïnstalleerde `requirements.txt` en een aanwezige
`cl100k_base`-cache:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_system_e2e.py' -v
```

Op bibib gebruikt de wrapper een expliciete cache. Geef voor bovenstaande
opdracht daar dezelfde bestaande cache mee:

```bash
TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken .venv/bin/python -m unittest discover -s tests -p 'test_system_e2e.py' -v
```

De test is ook onderdeel van de gewone `unittest discover -s tests` en
`./start_tests.sh`. De zelfstandige opdracht duurt normaliter enkele seconden.
Bij een ontbrekende/corrupte cache faalt hij zichtbaar vóór runtime-start,
zonder download of skip. Vul de cache zo nodig **vooraf**, tijdens installatie
(met netwerk), met dezelfde interpreter en gewenste `TIKTOKEN_CACHE_DIR`:

```bash
.venv/bin/python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
```

Dit installatiecommando is geen onderdeel van de offline test. De test leest en
hashcontroleert de bestaande cache en kopieert die naar zijn tijdelijke omgeving;
hij verandert de oorspronkelijke cache niet. Het verwachte bestand/hash volgt
het gepinde `tiktoken==0.12.0`-contract. Een tokenizerupgrade moet dit expliciet
opnieuw valideren.

### Werkelijk bewezen pad

`tests/test_system_e2e.py` start `ingress_api.py --port 0 --db <temp>` als
subprocess. Een readiness-log met de werkelijk gebonden poort plus HTTP
`GET /health` vervangt een gegokte startup-sleep. Daarna maakt HTTP een Sherlock-run
en publiceert een synthetische UTF-8-fiche met `run_id` via de echte `/ingress`.
De controle leest de persistente queue en runkoppeling via een onafhankelijke
SQLite-connectie. De producer wordt gestopt voordat de consument start.

Een tweede subprocess start `ariadne.py daily` met expliciete tijdelijke DB,
output, lock en log. Dit gebruikt de echte centrale migraties, snapshot,
`flock`, tokenizer, crashsafe filepublicatie en finale transactie. Het controleert
één queue-item, de exacte consumentenpayload, Sherlock-provenance, bronarchief,
ISO-week/topic/part 1/revision 1, revisiehash en bronmembership, materialisatietijd-
koppeling en `processed`. Bronbytes en source-ID komen precies eenmaal voor.
Twee volgende lege CLI-runs laten alle DB-tabellen en artifactbytes/mtime gelijk.
De bestaande integratietests blijven rollback/orphan-retry en procesoverlap testen.

Alle beschrijfbare staat staat onder één `TemporaryDirectory`, met een uitsluitend
synthetisch token en een afzonderlijke child-environment. Processen worden ook bij
failure beëindigd en tijdelijke staat wordt opgeruimd. De test gebruikt loopback,
geen proxy; externe socketverbindingen zijn in beide child-processen geblokkeerd.
Foutmeldingen benoemen startup/ingest, queue, materialisatie, artifacts of provenance;
CLI-failures tonen stderr en de tijdelijke runtimelogs vóór cleanup.

De kleine productieaanpassing maakt bestaande `run_daily`-configuratie bereikbaar
via `daily --db --output --lock --log`; alle bestaande defaults blijven gelden.
Bij gelijktijdige consumenten moeten zij hetzelfde lockpad gebruiken. Ingress logt
na succesvolle bind het niet-geheime host/poort-readinesssignaal.

### Bewuste beperking

Dit is een verse tijdelijke database, geen bewijs voor elke historische
productiemigratie. De bestaande migratie- en hersteltests blijven nodig. Ook
bewijst één fiche geen overflow-, belasting- of volledige redactionele kwaliteit.
Een herhaalde **POST** is geen idempotente retry: iedere succesvolle POST maakt
volgens het bestaande contract een nieuw item. De replaycontrole herhaalt de
consument na bevestigde verwerking, zonder opnieuw te publiceren of statussen
terug te zetten.

Niet getest zijn de vaste bibib-shellwrappers/venv-paden, systemd, cron, publieke
tunnel/discovery, Sites-sync/publicatie, MCP/pluginregistratie, auth-secrets of
Sherlocks actieve instructies/scheduler. Daarvoor geldt de afzonderlijke
[deployment-smokeprocedure](plugin-deployment.md#operationele-deployment-smoke).
Een lokale `127.0.0.1`-call bewijst nooit de gepubliceerde pluginroute.
