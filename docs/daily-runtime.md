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

`days` blijft legacy audit/provenance voor werkelijk geproduceerde output.
Geen `days.status`, `attempts` of ontbrekend dagrecord bestuurt de queue.
Een succesvolle uitvoer registreert de oorspronkelijke fichedatums in `days`.
Een mislukte poging wordt afzonderlijk in `attempts` geregistreerd met de
uitvoerdatum; eerder succesvolle dagprovenance blijft intact. Historische
foutrecords blijven bewaard. Er is geen weekrapport of zeven-dagenvolledigheidsregel.

## Deterministische legacy-parts

Tot het nieuwe partmodel wordt gebouwd, groepeert Ariadne per oorspronkelijke
fichedatum en topic. Binnen iedere groep bepaalt de numerieke queue-ID de
bronvolgorde: `queue:2` komt vóór `queue:10`. Geen semantische sortering of
inhoudelijke deduplicatie. Hele fiches blijven intact.

Output staat onder `/home/weekendkrant/draden/YYYY_Www/topic_N/YYYY-MM-DD_PPPP.txt`.
Week en datum in het pad en de draadheader volgen de oorspronkelijke fichedatum,
ook bij verwerking in een latere week. Nieuwe parts beginnen bij
`MAX(threads.part) + 1` voor dezelfde oorspronkelijke datum/topic, of 1 wanneer
geen provenance bestaat. Alleen gecommitte SQLite-provenance telt, geen toevallig
bestand op disk. Reeds geregistreerde draadpaden worden beschermd.

Late fiches voegen nieuwe parts toe en wijzigen geen succesvolle draad.
Een retry van dezelfde snapshot krijgt dezelfde geplande paden en bytes zolang
voor die parts nog geen succesvolle provenance bestaat. Losse files na een fout
kunnen daarom deterministisch worden vervangen. Een gewijzigde snapshot kan
andere nieuwe bytes opleveren; eerder geregistreerde output blijft intact.

`tiktoken==0.12.0` met `cl100k_base` meet de volledige geserialiseerde draad,
inclusief header en bronafscheidingen. Draad plus 5.000 reserve is maximaal
35.000 inputtokens. Een te grote hele fiche faalt expliciet; niets wordt afgekapt.
Het toekomstige week/topic-partmodel met immutable revisies is nog niet gebouwd.

## Transactie en crashgedrag

De niet-blokkerende lokale `flock` op `/home/weekendkrant/ariadne.lock` beschermt
één Ariadne-consument. Het lockpad is in tests injecteerbaar en staat buiten de
applicatierepository. Er zijn geen Git-commando's, branchcontroles of
weekworktree-operaties nodig voor `daily`; ook een gewone applicatiemap volstaat.
DB, output en lock mogen niet in de applicatierepository staan.

Selectie, payloadvalidatie, `weave()` en filesystemwrites houden geen SQLite
write-transactie open. De producer kan via een afzonderlijke connection blijven
invoegen. Files worden via tempfile, file-fsync, atomische rename en directory-fsync
geschreven. Pas daarna begint een korte `BEGIN IMMEDIATE` voor de finale update.
Die controleert alle oorspronkelijke snapshot-IDs opnieuw op pending en commit provenance plus exact die IDs als processed in één transactie.
Na de snapshot toegevoegde items vallen buiten deze verwerking.

Een fout, inclusief commitfout, rollbackt queue- en provenance-updates. De fout
wordt gelogd en de CLI stopt niet-nul. Bij een onbeschrijfbare DB kan ook de
foutregistratie mislukken; logging blijft zichtbaar. Filesystem en SQLite zijn
geen gezamenlijke atomische transactie: losse bytes zonder provenance kunnen
achterblijven. Bewaar succesvolle draden en database samen. Verwijderde
succesvolle files worden niet automatisch gereconstrueerd.

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
