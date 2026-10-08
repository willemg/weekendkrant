# Dagelijkse backlogverwerking op bibib

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

`PRAGMA user_version=0` is de bestaande onversioneerde productie-DB. De runtime
maakt transactioneel het partmodel plus offers en zet de versie op **2**.
Schema 1 krijgt additief alleen de offertabel en bijbehorende triggers. Bestaande
partrows, revisies en bronmemberships blijven exact behouden. Heropenen is
idempotent; onbekende nieuwere versies worden geweigerd.
Een verse DB krijgt legacy-, ingress- en parttabellen. Geen extern framework.
Zie het [exacte schema en auditcontract](audit-trail.md#partschema-versie-2).

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

Verwijder **handmatig** de obsolete zondagregel uit de crontab op bibib:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

Behoud voorlopig de dagelijkse regel, met de hosttijdzone `Europe/Brussels`:

```cron
0 10 * * * /home/weekendkrant/app/start_ariadne.sh daily >/dev/null
```

`daily` is de enige huidige operationele Ariadne-taak. `prepare-week` bestaat niet
meer in de CLI. De code wijzigt geen crontab, verwijdert geen historische branches
of worktrees en installeert geen nieuwe zondagjob.

## Bewaarbeleid

De automatische achtwekenretentie, `prune_history()`, `week_report()` en `VACUUM`
zijn verwijderd. Startup/migratie verwijdert geen bestaande SQLite-rijen.
Alle bestaande data blijft behouden; er is voorlopig geen automatische opruiming.
Een toekomstig beleid wordt apart ontworpen rond bronarchief, partrevisies,
Leonardo-state, actieve dossiers, missies en callaudit.
