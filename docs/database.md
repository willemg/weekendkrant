# SQLite-database

Schema 10 voegt `executor_activations` en `dispatcher_policy` toe. Bestaande
schema-9-startreceipts worden met hun immutable contractteksten gekopieerd;
oude audit blijft behouden. Zie [migratie en policy](dispatcher.md).

De database bewaart operationele state van Weekendkrant: ontvangst en verwerking
van ingress, dagpogingen, de onveranderlijke provenance van parts en offers,
en Sherlock-runs met daadwerkelijk gereviewde bronpagina's.
Het canonieke productiepad is `/home/weekendkrant/weekendkrant.sqlite3`.
Het databasebestand (inclusief eventuele journal/WAL-bestanden) hoort niet in Git.
Schema en migraties staan wel in Git; er worden geen productiegegevens meegeleverd.

## Eén migratieketen

`database.py` beheert alle DDL en `PRAGMA user_version`. De actuele versie is **9**.
De genummerde SQL-bestanden in `migrations/` zijn de bron van waarheid:

| Versie | Migratie | Verantwoordelijkheid |
| --- | --- | --- |
| 1 | `001_parts_base.sql` | Historische parts, revisions, bronarchief, lidmaatschap en immutabilityregels |
| 2 | `002_part_offers.sql` | Historische offers en sealing-/immutabilitytriggers |
| 3 | `003_unified_runtime_schema.sql` | Voorheen ongeversioneerde daily- en ingress-tabellen |
| 4 | `004_sherlock_state.sql` | Sherlock-runs en daadwerkelijk gereviewde bronpagina's |
| 5 | `005_sherlock_fiches.sql` | Immutable Sherlock-run→queue-item-provenance |
| 6 | `006_source_materializations.sql` | Immutable UTC-materialisatietijd per gearchiveerd queue-item |
| 7 | `007_jobs.sql` | Generieke jobs, afzonderlijke attempts/claims en reconciliatieaudit |
| 8 | `008_job_operations.sql` | Immutable control-plane-operation receipts |
| 9 | `009_sherlock_executor.sql` | Immutable Sherlock-opdrachten, contractsnapshots, run/job/attempt-binding en activatiereceipts |

De historische nummering blijft behouden. Versie 0 kan een lege database zijn,
maar ook reeds de voorheen ongeversioneerde runtime-tabellen bevatten.
Versies 1 en 2 worden additief aangevuld. Versie 3 accepteert bestaande
runtime-tabellen met het historische schema en maakt ontbrekende tabellen aan.
Een afwijkende bestaande runtime-tabel wordt geweigerd, zonder deze te herbouwen.
Migratie 4 voegt alleen `sherlock_runs` en `sherlock_sources` toe; bestaande
schemaobjecten en gegevens blijven ongemoeid. Een scratch-build doorloopt dezelfde
keten. Op de actuele versie is opnieuw migreren een no-op.
Een onbekende hogere versie wordt geweigerd.

Elke stap draait in een eigen `BEGIN IMMEDIATE`-transactie. De versie wordt binnen
de schrijflock gelezen, zodat gelijktijdige initialisaties dezelfde migratie niet
dubbel uitvoeren. DDL en versie worden samen gecommit; bij fouten wordt de hele
stap teruggedraaid. Eerder succesvol afgeronde stappen blijven behouden. Er zijn
geen resets, destructieve rebuilds of verwijderingen van bestaande gegevens.
Foreign keys worden op de migratieconnection ingeschakeld. Aanroepen met een
actieve transactie worden geweigerd om onbedoelde commits te vermijden.

## Opbouwen en migreren

Vanaf de repositoryroot, met de bestaande venv:

```bash
.venv/bin/python database.py --db /tmp/weekendkrant.sqlite3
```

Een ontbrekend bestand of lege database wordt volledig opgebouwd. Hetzelfde
commando is veilig opnieuw uitvoerbaar en migreert bestaande databases:

```bash
.venv/bin/python database.py --db /home/weekendkrant/weekendkrant.sqlite3
```

Maak vóór een productie-upgrade een consistente SQLite-back-up (bijvoorbeeld met
SQLite's backup-API). Stop indien nodig schrijvende diensten en cronruns om
gelijktijdige wijzigingen tijdens de upgrade te voorkomen. Voer de centrale
migratie uit met het bovenstaande commando en start gestopte diensten daarna
weer. Controleer vervolgens `PRAGMA user_version`, `PRAGMA integrity_check`
(verwacht `ok`) en `PRAGMA foreign_key_check` (verwacht een leeg resultaat).
De tests gebruiken uitsluitend synthetische databases.

Runtime gebruikt dezelfde `migrate(connection)` via `daily.database()` en
`IngressQueue`. De publieke `parts.migrate` en `parts.SCHEMA_VERSION` zijn
compatibiliteitsexports uit de centrale module; ze beheren geen eigen schema.

## Tabellen en regels

| Tabel | Verantwoordelijkheid |
| --- | --- |
| `parts` | Identiteit per week/topic/part, open/gesloten status en actieve revisie |
| `part_revisions` | Onveranderlijke logische revisies, canoniek renderpad, hash en tokenbudget; historische fysieke kopieën mogen ontbreken, zie [fase 6.5](revision-storage.md) |
| `source_archive` | Onveranderlijke oorspronkelijke bronbytes en provenance per queue-ID |
| `revision_sources` | Onveranderlijke, geordende bronlidmaatschappen per revisie |
| `part_offers` | Eén onveranderlijk aanbod per part van een geregistreerde actieve revisie |
| `days` | Dagstatus, week, commit-/manifesthash en eventuele fout |
| `attempts` | Verwerkingspogingen, status, fout en registratietijd |
| `threads` | Historische draadregistraties, dag, topic/part, hash en tokenbudget |
| `sources` | Historische bronregistraties en positie binnen een draad |
| `ingress_queue` | Ontvangen JSON-payloads, ontvangstmoment en verwerkingsstatus |
| `sherlock_runs` | Oplopende run-ID, topic, start-/eindtijd en uitvoeringsstatus |
| `sherlock_sources` | Unieke canonieke bron-URL, oorspronkelijke URL, run/topic, reviewtijd, optionele titel, outcome en rationale |
| `sherlock_fiches` | Eén immutable `queue_item_id`→`run_id`-koppeling per expliciet gekoppelde fiche |
| `source_materializations` | Eén immutable `queue_id`→`materialized_at`-record voor iedere nieuwe succesvolle Ariadne-materialisatie |

De partidentiteit is uniek; `one_open_part` staat maximaal één open part per
week/topic toe. Revisies hebben unieke paden, positieve revisienummers en
niet-negatieve tokenbudgetten; broncontent moet een BLOB zijn. Membership heeft
unieke posities en bronnen per revisie. Samengestelde foreign keys koppelen de
actieve revisie, membership en offers aan bestaande revisies. De historische
triggers bewaren partidentiteit, verbieden heropening, bewaken voortschrijdende
actieve revisies en verzegelen membership. Zes provenance-triggers verbieden
updates/verwijderingen van revisies, bronarchief en membership. Vijf offer-triggers
valideren en verzegelen het aanbod en verbieden wijzigen/verwijderen ervan.
Alle bestaande constraints en defaults zijn ongewijzigd overgenomen.

## Minimale Sherlock-state

`sherlock_state.SherlockState(connection)` gebruikt de centrale migratieketen bij
initialisatie. De caller beheert en sluit de connection. Elke publieke operatie
vereist een connection zonder actieve transactie. Mutaties beheren zelf een korte
`BEGIN IMMEDIATE`, commit en rollback; een fout commit geen gedeeltelijke operatie.
Runcontrole en broninsert vallen onder dezelfde schrijflock, zodat afsluiten en
registreren niet langs elkaar heen kunnen lopen. De opslaglaag bevat geen DDL.

- `start_run(topic)` accepteert integer 1, 2 of 3 en retourneert een oplopende ID.
- `finish_run(run_id, status)` sluit een `running` run precies één keer af als
  `completed` of `failed`, met eindtijd. Onbekende of afgesloten runs worden geweigerd.
- `already_reviewed(url)` canonicaliseert en retourneert een boolean. Deze lookup
  reserveert niets; tussen lookup en registratie kan een andere run dezelfde bron
  registreren. De unieke URL-constraint beslist bij insert.
- `record_reviewed_source(run_id, topic, url, outcome, rationale, title=None)`
  canonicaliseert binnen de opslaggrens en retourneert de canonieke URL. Alleen een
  bestaande `running` run met hetzelfde topic is toegestaan. Outcome en rationale
  moeten niet-lege tekst zijn en blijven exact bewaard; de titel mag ontbreken.

Ongeldige invoer of runstate geeft `ValueError`. Een duplicate canonieke URL geeft
`sqlite3.IntegrityError` en overschrijft geen eerdere audit. Topic en runstatus
hebben databaseconstraints; een running run heeft geen eindtijd, een afgesloten
run wel. `run_id` is een foreign key. De opslaglaag bewaakt aanvullend de topicmatch
met de run en weigert registratie na afsluiting. Alle door de opslaglaag geschreven
timestamps zijn UTC ISO 8601: `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`.

Registreer uitsluitend pagina's die daadwerkelijk inhoudelijk gereviewd zijn.
Een zoekresultaat, snippet of ongeopende kandidaat is geen gereviewde bron.
De caller is verantwoordelijk voor die inhoudelijke voorwaarde; de opslaglaag kan
niet vaststellen of een pagina gelezen is. Outcome en rationale zijn compacte,
controleerbare beslisnotities, geen opslag van interne redeneerprocessen.
Reeds geregistreerde reviews blijven bewaard als de run later faalt. Bij afbreken
vóór registratie blijft de bron beschikbaar voor een volgende run. Een afgebroken
run kan `running` blijven totdat een caller hem expliciet afsluit; er is geen TTL
of automatisch herstelmechanisme.

### URL-identiteit

De pure standaardbibliotheekfunctie `canonicalize_url(url)` accepteert absolute
HTTP(S)-URLs met een geldige hostname en zonder credentials. Onbruikbare URLs,
witruimte/controltekens, backslashes, ongeldige procent-escaping en ongeldige
poorten worden expliciet geweigerd. Scheme en hostname worden lowercase, de
standaardpoort (HTTP 80, HTTPS 443) en fragmenten verdwijnen. Querykeys worden
voor herkenning percent-gedecodeerd en hoofdletterongevoelig vergeleken:
`utm_*`, `fbclid`, `gclid` en `trk` worden verwijderd. Alle overige queryvelden
behouden hun volgorde, herhalingen en oorspronkelijke encoding. Paden worden
niet herschreven; trailing slashes blijven betekenisvol.

Bijvoorbeeld: `https://Example.COM:443/article?id=42&utm_source=x#deel` wordt
`https://example.com/article?id=42`. De oorspronkelijke aangeleverde URL blijft
apart in de audit staan. De canonieke URL is uniek over alle runs en topics heen.
Een andere URL over hetzelfde verhaal blijft een afzonderlijke toegestane bron.

Geen netwerkrequests, redirect-/AMP-detectie, domeinspecifieke regels of semantische
story-deduplicatie. Ook kandidaat-/claimstate, leases, retries, scheduling, APIs,
agentintegratie en Leonardo-state vallen buiten deze opslaglaag.

## Materialisatietijdprovenance (schema 6)

Migratie 6 voegt alleen `source_materializations`, een tijdindex en validatie-/
immutabilitytriggers toe. Er is geen backfill: bestaande bronbytes, memberships,
revisies, queue-statussen en overige provenance blijven intact. De tabel verwijst
naar `source_archive`; insert vereist een gearchiveerd, processed queue-item.
Update/delete en vervanging van een bestaande tijdregistratie worden geweigerd.
Nieuwe `daily`-materialisaties registreren alle geselecteerde queue-IDs met één
geobserveerd UTC-tijdstip in de korte finale transactie. Mislukte commit betekent
geen geregistreerde tijd, geen nieuwe actieve revisie en geen processed-status.
Historische bronontvangst, fichepayloaddatum, file-mtime of offertijd zijn geen
vervanging voor een onbekende materialisatietijd. Zie [telemetry](telemetry.md).

## Sherlock-ficheprovenance (schema 5)

Migratie 5 voegt alleen `sherlock_fiches`, een run-index en validatie-/immutability-
triggers toe. Bestaande queue-, bron-, run-, part- en revisiondata blijven intact;
er is geen backfill op basis van tijd of topic. Foreign keys verwijzen naar queue
en run. De inserttrigger vereist een bestaand queue-item en een `running` run;
update/delete en herattribueren via `INSERT OR REPLACE` worden geweigerd.
`IngressQueue.add(payload, run_id=...)` valideert het vier-velden-fichecontract
en de topicmatch, controleert de run onder `BEGIN IMMEDIATE` en commit queue-item
en koppeling samen. Runfinish gebruikt dezelfde SQLite-schrijflock. Een fout
laat geen half ontvangen fiche achter. Zonder `run_id` blijft ingress ongekoppeld.
Het mappingrecord blijft na processing en runafsluiting bestaan. Geen generieke
jobs of aanvullende source→fiche-koppeling worden geïntroduceerd.

## Generieke jobopslag (schema 7)

`jobs` bewaart stabiele rol-, input- en contractidentiteit plus lifecycle en outputs.
`job_attempts` bewaart afzonderlijke uitvoeringsclaims, unieke activatie/token,
vaste leases en terminale uitkomsten. `job_recoveries` bewaart immutable
reconciliatiebeslissingen met bewijsreferenties. De legacy-tabel `attempts`
blijft ongewijzigd Ariadnes runtimefoutaudit.

`jobs.JobStore` migreert via dezelfde centrale keten en gebruikt korte atomaire
transacties. Expiry blokkeert uitvoering, late resultaten worden gefenced en
een nieuwe attempt vereist expliciete veilige reconciliatie. Er is geen
backfill of dispatcher. Fase 4 voegt de control-plane toe; bestaande
runtimecontracten blijven behouden.
Zie [volledig lifecycle-, herstel- en testcontract](jobs.md).

## Control-plane-operationaudit (schema 8)

Migratie `008_job_operations.sql` voegt uitsluitend immutable `job_operations`
toe. Een globaal unieke operation-ID bindt het operatietype en een SHA-256 van
canonieke argumenten aan job-ID, eventueel attempt-ID, compact antwoord zonder
claimtoken en backendtijd. Lifecyclemutatie en receipt committen samen. Exacte
retries herhalen het bevestigde antwoord; gewijzigde argumenten geven conflict.
Tokens worden voor claimreplay uit de bestaande attempttabel gelezen.

Geen backfill of mutatie van bestaande tabellen, jobs of attempts. Upgrade van 7
naar 8, verse opbouw, herhaalde migratie en rollback bij mislukte DDL zijn getest.
`user_version=8` en de nieuwe tabel/triggers committen samen. Zie
[control-protocol](jobs.md#fase-4-protocol-identiteit-en-operation-receipts).

## Sherlock-executor (schema 9)

Vier additieve tabellen: `sherlock_contracts` (inhoud met SHA-256-ref),
`sherlock_assignments` (job/topic/datum/contractrefs), `sherlock_job_runs`
(run→job/attempt, met unieke attemptbinding) en `sherlock_activations`
(operation/activation-ID, tokenloze receipt en backendtijd). UPDATE, DELETE en
REPLACE zijn verboden; relaties gebruiken foreign keys. Geen legacy-backfill.
Bronnen en fiches blijven via hun bestaande run_id gekoppeld. Job, attempt, run,
assignment en startreceipt committen samen. DDL en user_version=9 committen samen;
een fout houdt versie 8 intact. Bestaande gegevens blijven bytegetrouw behouden.
Zie [Sherlock-executor](sherlock-executor.md) voor recovery- en testgrenzen.

## Volgende schemawijzigingen

Geen ad-hoc DDL in featuremodules. Iedere schemawijziging krijgt een nieuwe,
expliciet genummerde migratie en een verhoging van `database.SCHEMA_VERSION`.
Wijzig reeds uitgebrachte migraties niet. Test zowel scratch-build als upgrades,
dataretentie, idempotentie en rollback. Gebruik geen apart testschema als bootstrap:
productie, CLI en nieuwe databases gebruiken dezelfde migratiecode.
