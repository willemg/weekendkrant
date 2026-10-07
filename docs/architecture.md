# Architectuur

## Doel

Weekendkrant moet nieuws over meerdere interessegebieden gedurende de week verzamelen en daar uiteindelijk een leesbaar weekendmagazine van maken.

De architectuur probeert twee zaken tegelijk te optimaliseren:

- **kwaliteit**: bronnen bewaren, claims controleren, ruimte laten voor echte synthese;
- **kost**: dure modellen alleen inzetten waar hun intelligentie werkelijk nodig is.

## Hoofdflow en migratiestatus

Het doeltransport is `Sherlock -> HTTPS ingress-API -> SQLite queue -> Ariadne`.
Daarna volgen lokale thematische draden, Leonardo, Striktland en zo nodig één
Minos-herschrijving. De volledige Leonardo-input blijft maximaal 35.000 tokens.

De producerkant is geïmplementeerd: `GET /health` en bearer-beveiligde
`POST /ingress` bewaren JSON-objecten persistent als `pending`. De API bindt
standaard op `127.0.0.1:8000`. `ingress_tunnel.py` start en superviseert een afzonderlijk `cloudflared`-proces
voor externe HTTPS-bereikbaarheid. Het programma installeert geen binary of service.
Het verwachte token komt uitsluitend uit `WEEKENDKRANT_INGRESS_TOKEN`.
De publieke interface laat producers schrijven, maar biedt geen `GET /queue`.

Ariadne consumeert de queue rechtstreeks lokaal via `IngressQueue`:
`Sherlock -> MCP ingress -> ingress_queue.pending -> Ariadne daily -> lokale draden -> ingress_queue.processed`
`daily` verwerkt alleen vandaag in Europe/Brussels, zonder Git-transport,
manifestpolling of weekworktree. Zie [ingress-runtime](ingress-runtime.md) en
[het dagelijkse contract](daily-runtime.md). De oude `closed`-route is niet meer operationeel.

## Scheiding tussen determinisme en intelligentie

Ariadne vormt de harde grens tussen de voorspelbare softwarelaag en de generatieve modellen.

Ariadne mag geen nieuws begrijpen, waarderen of samenvatten. Haar taken moeten reproduceerbaar zijn:

- pending queue-items van vandaag lokaal lezen;
- items per vooraf gekend onderwerp bundelen;
- eenvoudige technische deduplicatie uitvoeren indien nodig;
- tokenaantallen berekenen;
- draden splitsen voordat de ingestelde tokenlimiet wordt overschreden;
- vastleggen wat verwerkt werd.

Alle semantische interpretatie ligt vóór of na Ariadne:

- Sherlock doet de eerste semantische selectie en broncompressie;
- Leonardo doet de synthese;
- Striktland doet verificatie;
- Minos doet alleen herstel.

## GitHub en lokale werkstaat

Git/GitHub blijft voor code, ontwerpdocumentatie, weekbranches, worktrees,
auditbare redactionele output en krantartefacten. GitHub is niet langer het
gekozen transportmechanisme voor Sherlock-fiches: SQLite is de persistente
transportqueue. Een weekbranch is geen queue. GitHub verzorgt daarnaast uitsluitend
service discovery via `config/ingress-endpoint.json` op `main`:

`cloudflared Quick Tunnel -> actuele URL -> discoverybestand op GitHub -> MCP-plugin`

De plugin Weekendkrant Ingress leest steeds de vaste raw GitHub-URL, en stuurt
fiches rechtstreeks door de tunnel naar de API. Sherlock kent alleen de MCP-tool.
Het discoverybestand bevat geen secret; de bearer-token blijft in de secretopslag
van bibib/Sites. Na reboot vervangt de publisher automatisch de oude tunnel-URL.

De publisher gebruikt een zelfstandige tijdelijke shallow clone met GitHub SSH,
buiten `app` en zonder `git worktree`. Alleen het discoverybestand wordt gecommit
en naar `main` gepusht. Een gelijktijdige remote wijziging stopt veilig zonder
force of rebase. Er wordt geen Git-opdracht op de hoofdrepo of weekworktree uitgevoerd.
De tijdelijke clone verdwijnt na publicatie of fout; systemd `RuntimeDirectory`
ruimt bij de gedocumenteerde productie-unit ook na een harde crash op.

Afgeleide thematische draden blijven in de observatiefase lokaal. SQLite bewaart
zowel de nieuwe transportqueue als Ariadnes bestaande operationele verwerkingsaudit,
in afzonderlijke tabellen. De database staat buiten Git en wordt niet gecommit.
Oude Git-fiches blijven historische artefacten; `daily` leest ze niet meer.

| Pad | Inhoud |
| --- | --- |
| `/home/weekendkrant/app/` | Primaire worktree op `main`: code, startscripts, tests en `.venv`. |
| `/home/weekendkrant/weekworktree/` | Enige beheerde weekworktree; bestaand redactioneel/versioneringsdoel; geen dagelijkse invoer. |
| `/home/weekendkrant/logs/` | Roterende Ariadne-logs. |
| `/home/weekendkrant/weekendkrant.sqlite3` | Persistente transportqueue en afzonderlijke operationele audittabellen. |
| `/home/weekendkrant/draden/` | Lokale afgeleide draden. |

Het queueschema staat in [de auditdocumentatie](audit-trail.md).

## Scheiding van code en weekworktree

De primaire worktree `app` blijft op `main`. Beide startscripts draaien altijd
vanuit deze map, met de interpreter uit `app/.venv`. Oude ingressbranches mogen
oude code bevatten: die wordt nooit uitgevoerd. Er wordt geen main-code in
bestaande ingressbranches gemerged of gerebased.

`prepare-week` controleert onder het gemeenschappelijke `flock` de volledige
registratie via `git worktree list --porcelain`. Er mogen maximaal twee
worktrees bestaan: `app` en het vaste beheerde pad `weekworktree`. Onverwachte
extra paden, een afwijkende branch, een ontbrekende of vergrendelde registratie
of een ongekoppeld bestaand pad leiden tot stoppen. Er wordt niet automatisch
gepruned of een willekeurige worktree verwijderd.

Voor een andere week verwijdert Ariadne eerst uitsluitend de beheerde schone
weekworktree met `git worktree remove`, zonder force. Ook untracked en genegeerde
bestanden beschermen de werkruimte tegen verwijdering. Daarna maakt ze op hetzelfde
pad de gewenste worktree aan. Een juiste worktree wordt hergebruikt. Bij fouten kan
tijdelijk alleen `app` overblijven; herhalen maakt de ontbrekende weekworktree
opnieuw aan. Weekbranches blijven tijdens de migratie behouden; branchsnoei staat los
van worktreesnoei en wordt in deze stap niet toegevoegd.

Worktrees delen de Git-objectdatabase: dit maakt geen volledige extra clone.
`daily` gebruikt uitsluitend het gemeenschappelijke slot en raakt de worktrees
niet aan. Alleen `prepare-week` controleert, koppelt en wisselt de weekworktree.

## Ingressbranch-lifecycle tijdens de overgang

Weekbranches en maximaal twee worktrees blijven bestaan voor hun bestaande
redactionele/versioneringsdoel. De naam `ingress/YYYY_Www` blijft voorlopig
ongewijzigd omdat de bestaande Git-runtime die gebruikt. Zij is geen onderdeel
van de nieuwe SQLite-queue.

Het vroegere ontwerp van branches als transportkanalen met `new`, `current` en
`grace` wordt niet verder als doeltransport uitgewerkt. Grace-catch-up en
branchsnoei zijn niet geïmplementeerd. Oude branches worden in deze PR niet
verwijderd; historische fiches en audit blijven behouden. Eventuele latere
branchopruiming moet die audit behouden en afzonderlijk worden uitgewerkt.

## Dagelijkse uitvoering

Sherlock publiceert zijn geselecteerde fiches via MCP vóór Ariadne om 10:00 start.
Ariadne neemt één SQLite-snapshot van `pending` voor de lokale datum, valideert de
volledige selectie en plant alle draden. Nul fiches geeft `success` met nul draden.
Er is geen gereedmarker en geen polling tot 13:00. Een ongeldige fiche of budgetfout
faalt de hele dag met `processing_error`; geselecteerde items blijven pending.

Draadbestanden worden atomisch geschreven vóór de databasecommit. Provenance,
dagstatus en de geselecteerde queue-statussen worden samen gecommit. Het
[crashvenster](daily-runtime.md#transactie-en-crashgedrag) kan losse bestanden
achterlaten; die zijn zonder succesvolle DB-registratie geen gepubliceerde output.
Een geslaagde dag is een no-op, ook als later nieuwe fiches voor die datum arriveren.
Oudere/toekomstige dagen worden niet verwerkt en late arrivals blijven pending.

Dagelijkse verwerking en weekvoorbereiding gebruiken hetzelfde niet-blokkerende
Linux `flock` in de gemeenschappelijke Git-map. De SQLite-transactie gebruikt
`BEGIN IMMEDIATE`; producers kunnen gedurende die korte verwerking niet schrijven.
Geen modellen, leases, retries of aanvullende queue-statussen.

## Zondagavond en overgang naar de volgende week

Op `bibib` is na de geslaagde handmatige preflight de volgende wekelijkse cronjob
ingesteld, met de hosttimezone `Europe/Brussels`:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

De weekjob start dus zondag om **22:00**, na de dagelijkse verwerking.
De geïmplementeerde uitbreiding leest de dagstatussen van de aflopende week uit SQLite.
Een timeout, verwerkingsfout of ontbrekend dagrecord maakt zichtbaar dat de oogst
niet aantoonbaar compleet is. Een ontbrekend dagrecord kan ook betekenen dat de
dagelijkse job helemaal niet heeft gedraaid. De weekjob leest hiervoor geen logtekst.

Een onvolledige dagoogst verandert de normale weekvoorbereiding niet en blokkeert
nooit het aanmaken en pushen van de volgende weekbranch. Gewone Git- en
runtimefouten blijven wel redenen om veilig te stoppen.

Bestaande weekbranches blijven behouden; `prepare-week` is niet nodig voor
Sherlock-transport. Historical catch-up en late-arrival-verwerking blijven buiten scope.

## Achtwekenretentie

`prepare-week --next-week` rapporteert eerst de aflopende Belgische ISO-week uit
SQLite en voert daarna retentie uit, onder hetzelfde slot. De bewaartermijn begint
op de maandag van die week minus zeven weken. Alle bestaande verwerkingsauditrecords met een eerdere lokale
datum worden verwijderd: eerst bronprovenance, dan draden, pogingen en dagstatus.
De verwijderingen staan in één transactie; pas na commit volgt `VACUUM` buiten de
transactie. Zo telt een ISO-jaarovergang inclusief week 53 correct mee. Ook oude
foutstatussen vervallen. Recente fouten blokkeren de volgende week niet.

Lokale draadbestanden worden niet verwijderd. Zonder bewaarde SQLite-provenance
zijn ze geen actieve verwerkingsoutput. `prepare-week --date` is een expliciete
voorbereiding en voert geen weekrapport/retentie uit. Database- of VACUUM-fouten
zijn runtimefouten en worden niet als gewone dagoogstfouten genegeerd.

De retentie raakt `ingress_queue` niet: pending fiches worden nooit door deze
auditretentie verwijderd. Queueopruiming volgt afzonderlijk.

## Kalender- en tijdzonecontract

Voor alle weekgebonden pipelinebeslissingen is `Europe/Brussels` de canonieke
kalenderzone. Sherlock en Ariadne moeten de lokale datum en daaruit het ISO-weekjaar
en weeknummer in deze zone bepalen.

De weekidentiteit heeft altijd vorm `YYYY_Www` en wordt gebruikt voor zowel branch
`ingress/YYYY_Www` als map `ingress/YYYY_Www/`. De overgang naar een nieuwe dag
of ISO-week gebeurt dus op lokale Belgische middernacht, inclusief de geldende
zomer- of wintertijd. UTC of de toevallige standaardtijdzone van een uitvoeromgeving
mag niet worden gebruikt om de actuele week te kiezen.

Een expliciet meegegeven kalenderdatum blijft toegestaan voor reproduceerbare tests,
herstel en handmatige uitvoering. `prepare-week --next-week` bepaalt de actuele
datum met `zoneinfo` expliciet in `Europe/Brussels` en kiest de maandag van de
eerstvolgende ISO-week, onafhankelijk van de hosttimezone. `--date` blijft exact
de opgegeven datum gebruiken; beide opties zijn wederzijds exclusief en één is verplicht.

## Logging

Alle runtime-logging van Ariadne loopt vanaf het begin via Python `logging`.
Productiecode schrijft geen ad-hoc `print()`-diagnostiek. Logrecords gebruiken
duidelijke niveaus zoals `DEBUG`, `INFO`, `WARNING`, `ERROR` en `CRITICAL`.

De loggingconfiguratie wordt centraal opgezet door het entrypoint; afzonderlijke
modules vragen alleen een logger op via `logging.getLogger(__name__)`. Exceptions
worden met stacktrace gelogd wanneer dat nuttig is voor diagnose.

De logbestanden staan buiten de Git-repository, onder
`/home/weekendkrant/logs/`, analoog aan Mail Sorter. Ze worden via een roterende
Python-loghandler beheerd zodat de opslag begrensd blijft. Cron hoeft daarom geen
eigen parallelle logarchieven op te bouwen.

De weekvoorbereiding schrijft naar `/home/weekendkrant/logs/ariadne.log` met een
`RotatingFileHandler`: maximaal 1 MiB per bestand en vier reservebestanden
(`.1` tot `.4`, samen circa 5 MiB). De map wordt zo nodig aangemaakt; de
uitvoerende gebruiker moet er schrijfrechten hebben. Het standaardniveau is `INFO`.
Dezelfde centrale configuratie kan expliciet met `configure_logging(level=logging.DEBUG)`
op `DEBUG` worden ingesteld; er is nog geen CLI-optie voor het niveau.
Ieder record bevat tijdstip, niveau, loggernaam en bericht, in UTF-8.
Start en succes worden gelogd; zowel verwachte als onverwachte runtime-fouten
uit de weekvoorbereiding worden bewust aan het unattended entrypoint afgehandeld
met context, stacktrace en exitcode 1. `SystemExit` en `KeyboardInterrupt`
vallen buiten deze exceptiongrens. Als de logging niet kan worden geïnitialiseerd, wordt de
fout via Python `logging` naar stderr geschreven en stopt Ariadne vóór voorbereiding.
Het JSON-resultaat blijft na succes op stdout verschijnen als gestructureerde
CLI-output; lifecycle- en diagnoseberichten lopen uitsluitend via logging.
CLI-help en argumentfouten blijven door `argparse` afgehandeld.

## Eerste implementatiestap: weekvoorbereiding

Het bestaande subcommand `prepare-week` bereidt de Git-weekwerkruimte voor
voor de verdere redactionele pipeline; `daily` heeft die niet nodig. Het vaste technische
padcontract is `ingress/<ISO-jaar>_W<week>/` op branch
`ingress/<ISO-jaar>_W<week>` (twee cijfers voor de week).
Een `.gitkeep` maakt de lege map versieerbaar. Dit legt het inhoudelijke
bronfichecontract niet vast: dat blijft onderdeel van de observatiefase.

De stap hergebruikt bestaande weekbranches en overschrijft geen oogst of auditrecord.
Het voorbereidingsrecord bewaart het uitgangscommit; het JSON-schema blijft ongewijzigd.
Het subcommand `prepare-week` voert de wekelijkse Git-workflow zelfstandig uit:
schone werkboom controleren, `fetch origin`, `main` uitsluitend fast-forward gelijk
maken aan `origin/main`, afzonderlijke weekworktree hergebruiken/vervangen, voorbereiding valideren,
alleen `.gitkeep` en het week-auditrecord committen indien nodig, en de weekbranch
naar `origin` pushen met upstream. Een nieuwe branch start op de bijgewerkte `main`.

Een bestaande weekremote wordt uitsluitend fast-forward gevolgd; bij een alleen
remote bestaande weekbranch wordt een lokale trackingbranch gemaakt. Bestaande
oogst blijft intact. Een lokale weekvoorsprong mag bij voorbereiding opnieuw
worden gepusht, bijvoorbeeld na een eerdere pushfout. Divergente weekhistory, vooruitgelopen/divergente `main`,
een vuile werkboom of conflicterende metadata leidt tot veilig stoppen.
Er is geen reset, force-push, automatische conflictmerge of commit van weekbestanden
op `main`. Herhaling maakt geen extra commit; push bevestigt telkens remote succes.
Een pushfout wordt met traceback gelogd en stopt niet-nul; de lokale commit blijft
beschikbaar voor een volgende poging. Git-identiteit en unattended authenticatie
zijn installatievoorwaarden. Eén schrijver per clone blijft vereist.

De zondagavondaanroep is
`/home/weekendkrant/app/start_ariadne.sh prepare-week --next-week`.
De crontab is na merge en een geslaagde handmatige preflight op `bibib`
geïnstalleerd zoals hierboven beschreven. De code bevat geen croninstallatie.
De dagelijkse verwerking is inmiddels toegevoegd als afzonderlijk subcommand `daily`.
Modelcalls blijven buiten scope.

## Dagelijkse lokale bundeling

De dagelijkse deterministische stap leest Sherlocks SQLite-queue en maakt daar
lokale draden met gereserveerde ruimte voor Leonardo-context van. Daarbij gelden voorlopig deze invarianten:

- bundelen gebeurt mechanisch op basis van expliciete metadata, niet op semantische interpretatie;
- dezelfde input en dezelfde Ariadne-versie leveren dezelfde bundels op;
- de **volledige** Leonardo-input blijft onder 35.000 tokens, dus inclusief vaste instructies,
  metadata en eventuele dossierstate;
- lokale bundels zijn afgeleide, disposable werkbestanden;
- verwerking en provenance worden in SQLite geregistreerd;
- geen bundel wordt automatisch naar GitHub teruggeschreven tijdens de observatiefase.

Het [dagelijkse runtimecontract](daily-runtime.md) legt bundelpaden, queuevalidatie,
SQLite-transacties, tokenizer, foutgedrag en concrete controlecommando’s vast.
De bestaande Ariadne-cronjobs zijn op bibib actief: `daily` dagelijks om 10:00
en `prepare-week --next-week` zondag om 22:00 Belgische tijd. De ingress-API draait op bibib via `weekendkrant-ingress.service`. De tunnelcomponent
heeft een afzonderlijke voorbeeld-unit in [ingress-runtime](ingress-runtime.md);
installatie daarvan gebeurt handmatig na merge.
