# SQLite-database

De database bewaart operationele state van Weekendkrant: ontvangst en verwerking
van ingress, dagpogingen en de onveranderlijke provenance van parts en offers.
Het canonieke productiepad is `/home/weekendkrant/weekendkrant.sqlite3`.
Het databasebestand (inclusief eventuele journal/WAL-bestanden) hoort niet in Git.
Schema en migraties staan wel in Git; er worden geen productiegegevens meegeleverd.

## Eén migratieketen

`database.py` beheert alle DDL en `PRAGMA user_version`. De actuele versie is **3**.
De genummerde SQL-bestanden in `migrations/` zijn de bron van waarheid:

| Versie | Migratie | Verantwoordelijkheid |
| --- | --- | --- |
| 1 | `001_parts_base.sql` | Historische parts, revisions, bronarchief, lidmaatschap en immutabilityregels |
| 2 | `002_part_offers.sql` | Historische offers en sealing-/immutabilitytriggers |
| 3 | `003_unified_runtime_schema.sql` | Voorheen ongeversioneerde daily- en ingress-tabellen |

De historische nummering blijft behouden. Versie 0 kan een lege database zijn,
maar ook reeds de voorheen ongeversioneerde runtime-tabellen bevatten.
Versies 1 en 2 worden additief aangevuld. Versie 3 accepteert bestaande
runtime-tabellen met het historische schema en maakt ontbrekende tabellen aan.
Een afwijkende bestaande runtime-tabel wordt geweigerd, zonder deze te herbouwen.
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
SQLite's backup-API). Stop voor de eerste uitrol de schrijvende diensten en cronruns,
voer de migratie uit en start ze daarna weer. De PR-tests gebruiken uitsluitend
synthetische legacydatabases; de echte database op bibib moet bij uitrol nog worden
gecontroleerd. Controleer versie en referentiële integriteit met
`PRAGMA user_version` en `PRAGMA foreign_key_check`.

Runtime gebruikt dezelfde `migrate(connection)` via `daily.database()` en
`IngressQueue`. De publieke `parts.migrate` en `parts.SCHEMA_VERSION` zijn
compatibiliteitsexports uit de centrale module; ze beheren geen eigen schema.

## Tabellen en regels

| Tabel | Verantwoordelijkheid |
| --- | --- |
| `parts` | Identiteit per week/topic/part, open/gesloten status en actieve revisie |
| `part_revisions` | Onveranderlijke revisies, bestandspad, hash en tokenbudget |
| `source_archive` | Onveranderlijke oorspronkelijke bronbytes en provenance per queue-ID |
| `revision_sources` | Onveranderlijke, geordende bronlidmaatschappen per revisie |
| `part_offers` | Eén onveranderlijk aanbod per part van een geregistreerde actieve revisie |
| `days` | Dagstatus, week, commit-/manifesthash en eventuele fout |
| `attempts` | Verwerkingspogingen, status, fout en registratietijd |
| `threads` | Historische draadregistraties, dag, topic/part, hash en tokenbudget |
| `sources` | Historische bronregistraties en positie binnen een draad |
| `ingress_queue` | Ontvangen JSON-payloads, ontvangstmoment en verwerkingsstatus |

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

## Volgende schemawijzigingen

Geen ad-hoc DDL in featuremodules. Iedere schemawijziging krijgt een nieuwe,
expliciet genummerde migratie en een verhoging van `database.SCHEMA_VERSION`.
Wijzig reeds uitgebrachte migraties niet. Test zowel scratch-build als upgrades,
dataretentie, idempotentie en rollback. Gebruik geen apart testschema als bootstrap:
productie, CLI en nieuwe databases gebruiken dezelfde migratiecode.
