# Audit trail en kwaliteitslabels

## Doel

De krant moet intern kunnen reconstrueren hoe een relevante feitelijke claim tot stand kwam.

Daarom krijgt iedere claim provenance: welke bronfiches eraan gekoppeld waren, welk model ze schreef, welke controle erop gebeurde en of een herschrijving nodig was.

## Persistente queue en lokale provenance

`ingress_queue` staat in `/home/weekendkrant/weekendkrant.sqlite3` naast de legacy
audittabellen. Het record bevat integer `id` (AUTOINCREMENT), `received_at` (UTC
met offset), `payload` (JSON-object als tekst) en `status` met default pending,
zonder pending-only CHECK. De producer schrijft pending en retourneert HTTP 201
na commit. Payloadopslag bewaart JSON-inhoud, geen exacte HTTP-bodybytes.

De consument verwerkt een snapshot van geldige pending fiches tot en met vandaag
in Europe/Brussels en markeert uitsluitend die IDs processed na succesvolle
output en provenance. De oorspronkelijke payloaddatum is provenance, geen
consumptievenster. Nieuwe en late arrivals blijven tot succesvolle verwerking
verwerkbaar. De publieke API heeft geen queue-leesendpoint.

Er is geen automatische retentie, dagvolledigheidscontrole of queueopruiming.
Bestaande data blijft behouden. `days` en `attempts` besturen de queue niet.
Een lege run maakt geen afgesloten dagrecord. Zie [runtimecontract](daily-runtime.md).

## Minimale kwaliteitslabels

### verified_first_pass

Leonardo formuleerde de claim en Striktland vond voldoende ondersteuning in de aangeleverde bronnen.

### inference

De passage is geen rechtstreeks bronfeit maar een expliciet herkenbare synthese, interpretatie of gevolgtrekking.

### rewritten_by_minos

Striktland vond de oorspronkelijke formulering onvoldoende ondersteund of strijdig met de bronnen. Minos heeft de passage daarna één keer herschreven.

Er volgt geen tweede automatische verificatieronde.

## Voorbeeld

```text
claim_042
status: rewritten_by_minos
initial_model: terra
checker: luna
checker_result: unsupported
rewrite_model: sol
source_refs: S17, S22
```

Een claim die meteen slaagt:

```text
claim_017
status: verified_first_pass
initial_model: terra
checker: luna
checker_result: verified
source_refs: S03
```

## Geen oneindige regressie

De controleketen stopt bewust na Minos.

```text
Leonardo -> Striktland -> eventueel Minos -> klaar
```

Als Minos alsnog een fout maakt, blijft dat een aanvaard restrisico. Het auditlabel maakt zichtbaar dat de passage al een correctieronde heeft doorlopen.

Bij uitzonderlijke of spectaculaire claims kan de lezer daardoor gericht zelf naar het oorspronkelijke bronmateriaal teruggaan.

## Audit trail als producteigenschap

Het audit trail is niet alleen debugging-informatie. Het maakt zichtbaar:

- welke claims probleemloos door de eerste controle kwamen;
- waar een model gecorrigeerd moest worden;
- welke passages inferenties zijn;
- welke oorspronkelijke bronnen bij een claim horen.

Daarmee wordt bronprovenance een structureel onderdeel van Weekendkrant.

## Partschema versie 2

De transactionele in-place migratie van schema 0 naar 2 maakt het partmodel
plus offers. Van schema 1 naar 2 worden alleen `part_offers` en offertriggers
toegevoegd. Bestaande tabellen, rows en bronbytes worden niet herschreven of
gereconstrueerd. Versie 2 is een no-op; onbekende nieuwere versies falen.

| Tabel | Contract |
| --- | --- |
| `parts` | Stabiel `id`, `week`, `topic`, `part`, `is_open`, `active_revision`. UNIQUE week/topic/part en partial UNIQUE week/topic WHERE is_open=1. Actieve revisie verwijst via composite FK naar dezelfde part. Gesloten parts worden nooit heropend; identiteit is immutable en de actieve pointer gaat alleen vooruit. |
| `part_revisions` | Immutable `(part_id, revision)`, uniek absoluut bestandspad, SHA-256 van exacte filebytes, tokens, tokenizer, reserved_tokens. |
| `source_archive` | Queue-ID als unieke provenance-identiteit, schema_version, oorspronkelijke date/topic, exacte UTF-8 content als BLOB en content-SHA-256. Geen FK naar ingress_queue. |
| `part_offers` | Stabiele AUTOINCREMENT `id`, UNIQUE `part_id`, `revision`, UTC `created_at`; composite FK naar de bestaande partrevision. Eén immutable lokaal handoff-record per part. |
| `revision_sources` | Per part/revision exact queue-ID en positie; UNIQUE positie én queue-ID binnen die revisie. FKs naar partrevision en bronarchief. |

UPDATE/DELETE-triggers bewaken immutable revisies, bronarchief, membership en offers.
Een offerinsert vereist de geregistreerde actieve revisie; de AFTER INSERT-trigger
sluit de part atomisch. Oude of fictieve revisies worden ook via directe SQL
geweigerd. Dubbele inserts en `INSERT OR REPLACE` van een bestaande offer-ID of
part-ID falen. Een offered actieve pointer kan niet meer veranderen; never-reopen
en de bestaande gesloten-partbescherming blijven gelden. Een reeds door overflow
gesloten part kan zijn actieve revisie nog aanbieden.

`PartStore.offer(part_id, revision)` beheert een korte write-transactie en geeft
bij identieke retry het bestaande record terug, inclusief ID en timestamp.
Een fout tijdens sealing of commit laat part, offeraudit en bronprovenance intact.
Het offer verwijst naar de bestaande hash, tokenmeting en membership; er worden
geen revisionfiles gewijzigd. Offered/sealed is een lokale auditstatus, geen
bewijs van een uitgevoerde of geslaagde Leonardo-call.

INSERT in reeds actieve of oudere revision-membership wordt geweigerd.
De opslag-API weigert een bestaande queue-ID met andere bytes of metadata.
Nieuw bronlidmaatschap wordt volledig geregistreerd voordat de actieve pointer
verschuift, binnen dezelfde transactie. Revisions zijn zonder queuepayloads
reproduceerbaar uit archief, geordende memberships en serializatiemetadata.

Iedere bronafscheiding noemt queue-ID, oorspronkelijke datum, SHA-256 en
aantal UTF-8 bytes. Het partformaat `WEEKENDKRANT-PART-1` noemt ISO-week,
topic, partnummer, revisienummer, tokenizer en reserve, zonder eigen datum.
Nieuwe bronvolgorde is `(payload.date, numerieke queue-ID)`; bestaande posities
blijven intact bij append-only revisiegroei.

Files ontstaan zonder SQLite write-transactie. Een korte finale transactie
controleert queue- en partstaat opnieuw en commit bronarchief, revisies,
memberships, partsluiting, actieve pointer en processed-status samen.
Een fout laat de vorige actieve revisie actief en eigen queue-items pending.
Losse files zonder geregistreerde provenance zijn orphans, nooit actieve output.
Zie [runtime en crashgedrag](daily-runtime.md#transactie-en-crashgedrag).

## Legacy SQLite-audittabellen

`days`, `threads` en `sources` blijven exact historische provenance; nieuwe
partverwerking schrijft daar niets meer in. Bestaande Git-hashes en
manifestverwijzingen blijven intact. `attempts` bewaart nog zichtbare
runtimefouten met uitvoerdatum en UTC-tijd, zonder nieuwe success-records.
Het is geen partauditmodel en geen selectie- of dagafsluitmechanisme.

Oude `YYYY-MM-DD_PPPP.txt` worden niet geconverteerd of geherinterpreteerd.
Nieuw verwerkte queue-items beginnen in het nieuwe schema bij part 1/revision 1
wanneer hun week/topic nog geen nieuwe-style part heeft. Geen oude rows of files
worden opgeruimd; er is geen automatische retentie of VACUUM.

## Geplande dossier-, state- en callaudit

Het [ontwerpbesluit van 8 oktober 2026](leonardo-memory-and-orchestration.md)
scheidt dagelijkse consumptie van dagoverschrijdende parts en langlevende dossiers.
Het geïmplementeerde partmodel registreert nu bronlidmaatschap over meerdere
dagen met immutable revisies. Stateversies, expliciete dossier-/missie-identifiers
en daadwerkelijke Leonardo-calls zijn nog niet geïmplementeerd. Het lokale
offer/seal-record is wel beschikbaar.

Iedere modelcall moet traceerbaar zijn naar prompt/modelconfiguratie, de werkelijk
aangeboden partversies en input-state, eventuele missiecontext, output en gebruik.
Reeds aangeboden versies blijven intact. Ook het laten groeien van een nog niet
aangeboden part mag een eerder succesvol geregistreerde versie niet ongeldig
maken bij een mislukte DB-commit. Het nieuwe partmodel bewaart geregistreerde revisies al crashsafe; concrete
callaudit volgt in een aparte stap.

Er is nu geen automatische retentie. Actieve state, open missies en benodigd
bronbewijs vragen een afzonderlijk, begrensd bewaarbeleid; dat wordt later ontworpen.
