# Fase 6.5: opslag-efficiëntie en revisieretentie

## Onderzoek en gekozen contract

De audit van de huidige Python-runtime vindt deze consumenten:

| Consument | Gebruik van revisies |
| --- | --- |
| `daily.run_daily` / `PartStore.active_sources` | Herneemt bronbytes uit `source_archive` via de membership van de actieve revisie; leest geen oude revisiefiles. Schrijft eerst de nieuwe file, commit daarna provenance en actieve pointer. |
| `PartStore.offer` / `offer_ready` | Registreert exacte actieve revisie en sealt; rendert/leest geen historische file. |
| `telemetry.parts_report` | Leest actieve metadata, hashes, tokenmetingen en offertellingen uit SQLite; geen historische file-I/O. |
| Sherlock-executor/control-plane | Gebruikt rol-/jobcontracten en bron-/fiche-audit; geen historische partfiles als input. |
| Tests | Enkele oudere backlog-/cadencetests veronderstelden permanente fysieke files. Die controleren nu exacte logische reconstructie, plus onveranderde bytes/mtime zolang een file behouden blijft. Systeemtests blijven de actieve fysieke output controleren. |

Er bestaat nog geen Leonardo-/Einstein-consument. Toekomstige consumenten moeten
historische revisies via reconstructie lezen en concrete actieve/offered input
respecteren. Een willekeurige externe lezer die buiten het runtime-slot een
historisch pad permanent open wil kunnen doen, valt niet onder dit contract.

De eenvoudigste strategie is **alle logische revisies bewaren, alleen vereiste
volledige files behouden**. Geen deltaformaat, compressielaag of schemawijziging:
`source_archive`, `part_revisions`, `revision_sources`, offers, hashes en tokenaudit
blijven volledig intact. `part_revisions.path` blijft het canonieke renderpad,
ook wanneer de historische fysieke kopie niet meer aanwezig is; het is geen
bestaan-garantie. Dit is geen verwijdering van logische historie.

## Nieuwe groei en bescherming

Iedere nieuwe revisie wordt eerst duurzaam geschreven en met membership,
bronarchief en queue-status gecommit. Pas daarna wordt de vorige actieve revisie
van diezelfde gegroeide part voor fysieke retirement gecontroleerd. Alle actieve
revisiefiles blijven staan, inclusief de actieve revisie van een gesloten part en
alle offered input. Overflow zonder pointergroei verwijdert niets. Reeds
historische files bij invoering worden niet automatisch door `daily` opgeruimd.

`revision_storage.reconstruct(db, part_id, revision)` rendert het bestaande
`WEEKENDKRANT-PART-1`-formaat uit geordende memberships en exacte UTF-8 bronbytes,
inclusief datum, bronhash, bytegrootte, revisieheader en reserve. De functie
controleert aaneengesloten posities, brontopic/schema/hash, volledige revisiehash,
tokenizer en tokenmeting met de gepinde tokenizer. Ontbrekende of afwijkende audit,
onbekende tokenizer/serialization en corrupte bytes geven een fout; ze geven
nooit toestemming om een file te verwijderen. Behoud de renderer en tokenizer
voor dit historische formaat ook bij een eventuele latere formaatwijziging.

Retirement vereist een byte-exacte reconstructie én een byte-exacte fysieke kopie.
Na die controle volgt onder dezelfde Ariadne-runtime-lock een korte SQLite
`BEGIN IMMEDIATE` met een nieuwe active-/offercontrole vóór unlink. Canonieke
paden binnen de expliciete dradenmap zijn verplicht; symlinks en gedeelde paden
worden geweigerd. Er wordt niet op `rev_*.txt` geglobd voor verwijdering.
Geen bronbytes, membership, hash, tokens, offerte of auditrij wordt gewijzigd.

## Crash, retry en bestaande data

- Fout vóór de materialisatiecommit: de oude actieve file blijft staan; een nieuwe orphan volgt het bestaande retrycontract.
- Crash na commit maar vóór unlink: een overbodige kopie kan blijven liggen. Normale verwerking is geldig; expliciete cleanup kan die later opruimen.
- Crash na unlink, ook vóór directory-fsync/DB-commit: er is geen auditmutatie om te verliezen. De historische revisie blijft exact reconstrueerbaar. Een na crash terugkerende directory-entry is alleen redundantie.
- Fout tijdens retirement: CLI/logging melden de fout; de eerder gecommitteerde materialisatie wordt niet teruggedraaid. Retry maakt geen dubbele bronnen. Gebruik de aparte cleanup voor achtergebleven kopieën.
- Herhaalde cleanup: een ontbrekende historische file is normaal en telt als `missing`; actieve/offered input als `protected`.

Er is geen schemamigratie nodig: schema 9 blijft gelijk, inclusief bestaande
immutabilitytriggers. De hele logische database blijft behouden. Bestaande
historische files worden uitsluitend door de onderstaande expliciete stap
verwijderd, nooit door startup/migratie. Losse orphans en legacy-dagbestanden
worden niet verwijderd. Backup moet SQLite met het volledige bronarchief en de
behouden actieve/offered files omvatten; alleen een verzameling fysieke
revisiefiles is geen volledige historische backup meer.

## Expliciete cleanup, standaard dry-run

Na applicatie-update en tests op bibib, als gebruiker `weekendkrant`:

```bash
cd /home/weekendkrant/app
.venv/bin/python -m revision_storage --db /home/weekendkrant/weekendkrant.sqlite3 --output /home/weekendkrant/draden
```

Dit opent uitsluitend een bestaande DB, gebruikt hetzelfde runtime-slot als
`daily` en rapporteert per revisie `eligible`, `missing` of `protected` met
logische filebytes. Het wijzigt geen auditdata, migreert niets en verwijdert niets.
Na inspectie van de dry-run kan de operator dezelfde opdracht met `--apply`
uitvoeren. Dat is een afzonderlijke, expliciete productieactie. Deze PR voert
geen productiecleanup uit.

Cleanup is per file hervatbaar, geen alles-of-niets-batch: bij een latere fout
kunnen eerder gecontroleerde kopieën al weg zijn. Alle historie blijft in SQLite.
Een runtime-lockconflict stopt direct; voer de opdracht later opnieuw uit.
De gerapporteerde bytes zijn bestandslengtes, geen meting van filesystemblokken,
compressie, backups of totale diskbezetting. Geen `VACUUM` of bronretentie.

Historische bytes kunnen zonder fysieke file worden gecontroleerd:

```python
import sqlite3
from revision_storage import reconstruct
with sqlite3.connect('/home/weekendkrant/weekendkrant.sqlite3') as db:
    exact_bytes = reconstruct(db, part_id=1, revision=1)
```

## Gemeten besparing en grenzen

Synthetische lokale proef: twintig opeenvolgende revisies van één part, telkens
een nieuwe bron met circa 1.000 bytes plus Unicode/CRLF. Alle twintig revisies
zijn gereconstrueerd en tegen hun audit gecontroleerd.

| Maatstaf | Bytes |
| --- | ---: |
| Alle volledige revisiefiles volgens het oude beleid | 246.562 |
| Behouden actieve file volgens fase 6.5 | 23.392 |
| Vermeden fysieke filekopieën | 223.170 (90,51%) |
| SQLite in dezelfde proef, ongewijzigd behouden | 278.528 |

Dit is geen productiemeting. Bij ongeveer gelijke bronbatches groeit de oude som
van volledige files kwadratisch met het aantal revisies, terwijl de behouden
actieve file met de partinhoud groeit. De verwachte besparing op revisiefiles is
ongeveer `1 - 2/(n+1)` bij `n` gelijke batches, met headeroverhead als afwijking.
Bronarchief, ingresspayloads, membership en overige SQLite-audit blijven ruimte
innemen; er wordt geen procentuele besparing op de totale productiedisk beloofd.
Na sealen blijven die concrete inputfiles behouden. Productiecontrole en een
werkelijke dry-runmeting blijven open.
