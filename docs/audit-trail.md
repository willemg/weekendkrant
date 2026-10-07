# Audit trail en kwaliteitslabels

## Doel

De krant moet intern kunnen reconstrueren hoe een relevante feitelijke claim tot stand kwam.

Daarom krijgt iedere claim provenance: welke bronfiches eraan gekoppeld waren, welk model ze schreef, welke controle erop gebeurde en of een herschrijving nodig was.

## Twee auditlagen

Weekendkrant maakt onderscheid tussen twee soorten auditinformatie:

1. **versioneerbare bootstrapinformatie** die nodig is om een wekelijkse Git-werkruimte
   reproduceerbaar voor te bereiden;
2. **operationele verwerkingsaudit** van Ariadne en latere pipeline-stappen.

Het bestaande `ingress-preparation.json` blijft voor de eerste categorie in Git.
Voor de tweede categorie wordt een lokale SQLite-database gebruikt. Die database kan
bijvoorbeeld vastleggen welke ingressfiches gezien of verwerkt zijn, uit welke fiches
een draad bestaat, hoeveel tokens ervoor werden gemeten en welke pipeline-stap werd
uitgevoerd.

Tijdens de observatiefase is deze database lokale operationele staat en wordt ze niet
naar GitHub gecommit. Het operationele schema voor dagelijkse bundeling staat hieronder.

## Persistente transportqueue

`ingress_queue` staat naast de bestaande audittabellen in
`/home/weekendkrant/weekendkrant.sqlite3`. Elk record bevat `id` (uniek intern
INTEGER PRIMARY KEY AUTOINCREMENT), `received_at` (UTC met offset), `payload`
(JSON-object als tekst) en `status` (`TEXT NOT NULL DEFAULT 'pending'`, zonder
beperkende CHECK-constraint). Deze producerstap schrijft uitsluitend `pending`.
Een succesvolle HTTP `201` volgt pas nadat de INSERT-transactie is gecommit. De interface bewaart de JSON-inhoud,
geen exacte HTTP-bodybytes of inhoudelijk gevalideerde ficheheader.

Dit is ontvangstregistratie, geen bewijs van Ariadne-verwerking. Ariadne leest
nog Git; lokale queueconsumptie volgt in een volgende PR. De publieke API heeft
geen queue-leesendpoint. De bestaande achtweken-auditretentie verwijdert geen
pending queue-items. Er is nog geen queueopruiming, lease of retryworkflow.

## Operationele dagstatus (bestaande Git-overgangsruntime)

Ariadne bewaart lokale datum, ISO-week en `success`, `timeout` of
`processing_error`. Een ontbrekend dagrecord bewijst geen succesvolle verwerking.
Een lege oogst slaagt alleen met een expliciet geldig Git-afsluitmanifest.
De zondagjob leest deze statussen, geen logtekst, en blokkeert de volgende
weekvoorbereiding niet wegens een onvolledige oogst. Historische catch-up en de
vroeger voorgestelde grace-/`missed`-overgangen zijn niet geïmplementeerd; zij
vormen geen contract voor de nieuwe transportqueue.

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

## Weekvoorbereiding (schema 1)

De eerste implementatie schrijft `audit/<jaar>_W<week>/ingress-preparation.json`:

```json
{
  "schema_version": 1,
  "week": "2026_W40",
  "branch": "ingress/2026_W40",
  "ingress_path": "ingress/2026_W40",
  "base_commit": "<volledige SHA van het uitgangscommit op de weekbranch>"
}
```

Dit registreert alleen de technische voorbereiding, geen verwerkte fiches,
bronverificatie of claimkwaliteitslabels. Het record krijgt geen kloktijd, zodat
herhaald uitvoeren dezelfde inhoud oplevert. Na commit maakt Git de wijziging
en het tijdstip traceerbaar. Een bestaand passend record blijft behouden,
ook na latere oogstcommits; een afwijkend record wordt geweigerd.

## Dagelijkse SQLite-audittabellen (bestaande Git-consument)

- `days`: één record per lokale datum, met ISO-week, status, remote commit-SHA,
  SHA-256 van het afsluitmanifest en eventuele foutmelding.
- `attempts`: historie van afgeronde pogingen binnen de bewaartermijn, met status, fout en UTC-tijd.
  Een herhaling van een geslaagde dag voegt geen poging toe. Een herstelde fout
  blijft hier zichtbaar, ook wanneer de actuele dagstatus daarna succes wordt.
- `threads`: absoluut lokaal pad, dag, topic, deelnummer, inhoudshash, gemeten
  tokens, tokenizer en gereserveerde tokens.
- `sources`: per dag en bronpad de exacte SHA-256, gekoppelde draad en positie.
  De `days.commit_sha` legt vast uit welke Git-snapshot de bytes kwamen.

Alle draden worden eerst deterministisch gepland. Binnen één SQLite-transactie
worden de draadbestanden via een tijdelijk bestand, fsync en atomische rename
gepubliceerd en worden alle provenance en de successtatus vastgelegd. Pas na de
commit is de dag succesvol. Een fout rolt de volledige transactie terug en schrijft
afzonderlijk `processing_error`; een ontbrekende melding na de deadline schrijft
`timeout`. Foutpogingen blijven binnen de bewaartermijn bewaard. Buiten Git staan zowel database als draden.

Bestandssysteem en SQLite vormen samen geen enkele atomische transactie. Een crash
of fout tijdens schrijven kan daarom losse afgeleide bestanden achterlaten, maar
geen succesvol dagrecord met gedeeltelijke provenance. Alleen bestanden die via
`threads` bij een succesvolle dag geregistreerd zijn, zijn gepubliceerde output.
Een herhaling overschrijft eventuele losse bestanden deterministisch. Bij hard
procesverlies vóór foutregistratie kan een dagrecord ontbreken; de weekjob meldt
ook dat als onvolledig. Eerdere succesvolle dagen worden nooit verwijderd.

Een geslaagde dag is idempotent en wordt niet opnieuw verwerkt; handmatig verwijderen
van succesvolle output wordt niet automatisch hersteld. Bewaar de database en
succesvolle draden samen. De huidige runtime biedt nog geen herstel- of
inhaalmechanisme voor oude dagen. Het toekomstige lokale consumentencontract wordt afzonderlijk uitgewerkt;
deze PR verandert geen verwerkingsstatussen of catch-up.

## Wekelijkse retentie

Deze retentie geldt uitsluitend voor de bestaande verwerkingsaudit, niet voor
`ingress_queue`. Na rapportage bewaart de zondagjob acht Belgische ISO-weken: de aflopende week en
zeven voorgaande weken. De ondergrens is de maandag van de aflopende week minus
zeven weken; records met een eerdere `day` vervallen, inclusief fouten en pogingen.
`sources`, `threads`, `attempts` en `days` worden in die volgorde in één transactie
opgeruimd, met foreign keys actief. Na commit volgt `VACUUM` buiten de transactie.
Een fout tijdens verwijderen rolt alles terug. Een VACUUM-fout verandert de reeds
gecommitte retentie niet en wordt als runtimefout gemeld.

Lokale draadbestanden blijven staan als opstartartefacten. Vervallen provenance
betekent dat die bestanden niet meer als actieve verwerkingsoutput gelden.
Er wordt geen oude week opnieuw verwerkt om provenance te reconstrueren.
