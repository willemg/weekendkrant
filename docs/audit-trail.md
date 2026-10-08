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

## Legacy SQLite-audittabellen

Deze tabellen blijven bestaan om bestaande data en huidige afgeleide output
leesbaar te houden tot het aparte part-/revisieschema wordt ontworpen:

- `days`: oorspronkelijke fichedatum, ISO-week en auditstatus voor geproduceerde
  output. `commit_sha` en `manifest_sha256` zijn NULL voor queueverwerking.
  Historische fout-/timeoutrecords blijven bewaard. Status bestuurt geen selectie.
- `attempts`: geslaagde outputregistraties en mislukte pogingen met fout en UTC-tijd.
  Success wordt per geproduceerde oorspronkelijke datum geregistreerd; fouten
  krijgen de uitvoerdatum. Lege runs voegen niets toe. Een late mislukte poging
  wijzigt eerdere succesvolle `days`-provenance niet.
- `threads`: absoluut pad, oorspronkelijke datum, topic, part, SHA-256, gemeten
  tokens, tokenizer en reserve. Gecommitte records bepalen volgende partnummers.
- `sources`: oorspronkelijke datum, `source_path` zoals `queue:2`, SHA-256 van de
  exacte UTF-8 contentbytes, draadpad en bronpositie. De bronvolgorde volgt
  numerieke queue-ID binnen datum/topic.

Files worden atomisch geschreven zonder SQLite write-transactie. Daarna
controleert één korte `BEGIN IMMEDIATE` alle snapshot-IDs opnieuw en registreert
provenance en processed-status samen. Fouten rollbacken die update; een volgende
run ziet oude pending fiches vanzelf opnieuw. Files zonder provenance kunnen
achterblijven en worden voor dezelfde snapshot deterministisch opnieuw geschreven.
Late arrivals krijgen volgende parts zonder bestaande succesvolle bytes te wijzigen.

`week_report`, `prune_history`, de achtwekenregel en automatische `VACUUM` zijn
verwijderd. Startup verwijdert geen bestaande rijen. Het historische Git-record
`ingress-preparation.json` wordt niet meer aangemaakt en is geen actieve runtime.
Historische branches en worktrees worden door deze cleanup niet verwijderd.
Bewaar database en succesvolle draden samen; zie [crashgedrag](daily-runtime.md#transactie-en-crashgedrag).

## Geplande dossier-, state- en callaudit

Het [ontwerpbesluit van 8 oktober 2026](leonardo-memory-and-orchestration.md)
scheidt dagelijkse consumptie van dagoverschrijdende parts en langlevende dossiers.
Het toekomstige schema moet bronlidmaatschap over meerdere dagen kunnen registreren,
met partrevisies, hashes, stateversies en expliciete dossier- en missie-identifiers.

Iedere modelcall moet traceerbaar zijn naar prompt/modelconfiguratie, de werkelijk
aangeboden partversies en input-state, eventuele missiecontext, output en gebruik.
Reeds aangeboden versies blijven intact. Ook het laten groeien van een nog niet
aangeboden part mag een eerder succesvol geregistreerde versie niet ongeldig
maken bij een mislukte DB-commit. Hiervoor is apart migratie- en crashherstelontwerp
nodig; de huidige dagtabellen implementeren dit nog niet.

Er is nu geen automatische retentie. Actieve state, open missies en benodigd
bronbewijs vragen een afzonderlijk, begrensd bewaarbeleid; dat wordt later ontworpen.
