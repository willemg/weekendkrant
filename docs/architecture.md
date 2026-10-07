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
standaard op `127.0.0.1:8000`. Een afzonderlijke tunnel/reverse proxy verzorgt
externe HTTPS-bereikbaarheid. Deze infrastructuur behoort niet tot de Python-app;
er is geen Cloudflare-configuratie of service-installatie in deze stap.
Het verwachte token komt uitsluitend uit `WEEKENDKRANT_INGRESS_TOKEN`.
De publieke interface laat producers schrijven, maar biedt geen `GET /queue`.

Ariadne zal de queue rechtstreeks lokaal via de database-interface consumeren.
Die consumptie en Sherlocks omschakeling zijn **nog niet geïmplementeerd**.
`daily` leest voorlopig nog de bestaande Git-fiches en afsluitmanifesten;
API-fiches worden nu opgeslagen maar nog niet door Ariadne verwerkt.
Zie [ingress-runtime](ingress-runtime.md) en
[de bestaande overgangsruntime](daily-runtime.md).

## Scheiding tussen determinisme en intelligentie

Ariadne vormt de harde grens tussen de voorspelbare softwarelaag en de generatieve modellen.

Ariadne mag geen nieuws begrijpen, waarderen of samenvatten. Haar taken moeten reproduceerbaar zijn:

- nieuwe queue-items lokaal lezen (volgende implementatiestap);
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
transportqueue. Een weekbranch is geen queue.

Afgeleide thematische draden blijven in de observatiefase lokaal. SQLite bewaart
zowel de nieuwe transportqueue als Ariadnes bestaande operationele verwerkingsaudit,
in afzonderlijke tabellen. De database staat buiten Git en wordt niet gecommit.
De huidige Git-fiches blijven beschikbaar zolang `daily` daarvan afhankelijk is.

| Pad | Inhoud |
| --- | --- |
| `/home/weekendkrant/app/` | Primaire worktree op `main`: code, startscripts, tests en `.venv`. |
| `/home/weekendkrant/weekworktree/` | Enige beheerde weekworktree; bestaand redactioneel/versioneringsdoel en tijdelijk nog invoer voor de Git-consument. |
| `/home/weekendkrant/logs/` | Roterende Ariadne-logs. |
| `/home/weekendkrant/weekendkrant.sqlite3` | Persistente transportqueue en afzonderlijke operationele audittabellen. |
| `/home/weekendkrant/draden/` | Lokale afgeleide draden. |

Het queueschema staat in [de auditdocumentatie](audit-trail.md).

## Scheiding van code en weekworktree

De primaire worktree `app` blijft op `main`. Beide startscripts draaien altijd
vanuit deze map, met de interpreter uit `app/.venv`. Oude ingressbranches mogen
oude code bevatten: die wordt nooit uitgevoerd. Er wordt geen main-code in
bestaande ingressbranches gemerged of gerebased.

Iedere Ariadne-runtime controleert onder het gemeenschappelijke `flock` de volledige
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
De dagelijkse taak kan de actuele bestaande week zelf aankoppelen en is dus niet
afhankelijk van een zondagrun. Na zondagavond kan tijdelijk de volgende week
gekoppeld zijn; de dagelijkse taak bepaalt haar doel opnieuw volgens de Belgische
kalender. Zie de [migratiehandleiding](daily-runtime.md#migratie-van-bibib-na-merge).

## Ingressbranch-lifecycle tijdens de overgang

Weekbranches en maximaal twee worktrees blijven bestaan voor hun bestaande
redactionele/versioneringsdoel. De naam `ingress/YYYY_Www` blijft voorlopig
ongewijzigd omdat de bestaande Git-runtime die gebruikt. Zij is geen onderdeel
van de nieuwe SQLite-queue.

Het vroegere ontwerp van branches als transportkanalen met `new`, `current` en
`grace` wordt niet verder als doeltransport uitgewerkt. Grace-catch-up en
branchsnoei zijn niet geïmplementeerd. Oude branches worden in deze PR niet
verwijderd; de runtime leest nog hun fiches en audit. Eventuele latere
branchopruiming moet die audit behouden en afzonderlijk worden uitgewerkt.

## Dagafsluiting en dagelijkse uitvoering (bestaande Git-overgangsruntime)

Sherlock start momenteel dagelijks rond 08:00 in `Europe/Brussels`, met een flexibel
starttijdstip. Dat is geen gegarandeerde eindtijd. Ariadne mag de dagoogst pas
verwerken nadat Sherlock expliciet heeft gemeld dat hij voor die datum klaar is.

Sherlock publiceert de gereedmelding op de bijbehorende weekbranch als laatste,
nadat alle fiches van die dag succesvol zijn gepusht. De melding noemt de lokale
datum en geldt ook voor een dag zonder geselecteerde fiches. Na die melding mag
Sherlock voor die datum niets meer toevoegen. Bij een onvolledige of mislukte
publicatie geeft hij geen gereedmelding. Het bestand is `ingress/YYYY_Www/closed/YYYY-MM-DD.json`: een versie-1-manifest
met datum, week en exacte fichepaden plus SHA-256-hashes. Zie
[het concrete contract](daily-runtime.md#sherlocks-afsluitcontract-versie-1). Het is geen bronfiche.

De dagelijkse cronjob start Ariadne één keer om **10:00 Belgische tijd**. Het proces
controleert meteen de gereedmelding voor die dag op de actuele remote weekbranch.
Ontbreekt de melding, dan slaapt Ariadne tien minuten en haalt daarna de remote
stand opnieuw op voor de volgende controle. Dit herhaalt ze gedurende maximaal
drie uur vanaf de start. Er komen geen afzonderlijke cronaanroepen elke tien minuten.

Na fetch synchroniseert Ariadne de afzonderlijke actuele weekworktree veilig via
fast-forward en controleert daarin de gereedmelding. Alleen na een geldige melding
verwerkt ze de afgesloten dagoogst. Een reeds succesvol
verwerkte dag wordt niet dubbel verwerkt. Een vuile werkboom of conflicterende
Git-history mag niet met reset, force-push of automatische conflictmerge worden
opgelost. De huidige week volgt uit de Belgische kalender, niet uit de branch
waarop de clone toevallig achterbleef na weekvoorbereiding.

Bij een start om 10:00 eindigt het wachten uiterlijk om 13:00. Dat begrenst alleen
het wachten: verwerking die net vóór de deadline begint, kan later eindigen.
Zonder gereedmelding wordt niets verwerkt. Bij het verstrijken van de wachttijd
registreert Ariadne de fout voor de betreffende datum in SQLite, schrijft ze een
diagnostische melding via de bestaande logging en stopt ze met een niet-nul exitcode.
Ook succesvolle verwerking en verwerkingsfouten krijgen een persistente dagstatus;
zie [de operationele dagstatus](audit-trail.md#operationele-dagstatus-bestaande-git-overgangsruntime).

Dagelijkse verwerking en wekelijkse voorbereiding gebruiken dezelfde vergrendeling,
zodat nooit twee Ariadne-processen tegelijk aan dezelfde clone werken. Het Linux-`flock` staat in de gemeenschappelijke Git-map en blijft gedurende
de hele taak vastgehouden. Een tweede proces stopt direct.

## Zondagavond en overgang naar de volgende week

Op `bibib` is na de geslaagde handmatige preflight de volgende wekelijkse cronjob
ingesteld, met de hosttimezone `Europe/Brussels`:

```cron
0 22 * * 0 /home/weekendkrant/app/start_ariadne.sh prepare-week --next-week >/dev/null
```

De weekjob start dus zondag om **22:00**, ruim na het dagelijkse wachtvenster.
De geïmplementeerde uitbreiding leest de dagstatussen van de aflopende week uit SQLite.
Een timeout, verwerkingsfout of ontbrekend dagrecord maakt zichtbaar dat de oogst
niet aantoonbaar compleet is. Een ontbrekend dagrecord kan ook betekenen dat de
dagelijkse job helemaal niet heeft gedraaid. De weekjob leest hiervoor geen logtekst.

Een onvolledige dagoogst verandert de normale weekvoorbereiding niet en blokkeert
nooit het aanmaken en pushen van de volgende weekbranch. Gewone Git- en
runtimefouten blijven wel redenen om veilig te stoppen.

Zolang `daily` Git leest, blijven bestaande fiches, manifesten en branches
behouden. De huidige code verwerkt na de weekovergang uitsluitend de actuele dag.
De oude voorgestelde branchgrace is geen geïmplementeerde catch-up en geen
ontwerp voor de SQLite-queue.

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
auditretentie verwijderd. Queueconsumptie en -opruiming volgen afzonderlijk.

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
die tijdens de migratie nog door `daily` wordt gebruikt. Het vaste technische
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
worden gepusht, bijvoorbeeld na een eerdere pushfout; dagelijkse verwerking weigert
een lokale voorsprong. Divergente weekhistory, vooruitgelopen/divergente `main`,
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

## Dagelijkse lokale bundeling (bestaande Git-consument)

De dagelijkse deterministische stap leest Sherlocks bestaande ingress en maakt daar
lokale draden met gereserveerde ruimte voor Leonardo-context van. Daarbij gelden voorlopig deze invarianten:

- bundelen gebeurt mechanisch op basis van expliciete metadata, niet op semantische interpretatie;
- dezelfde input en dezelfde Ariadne-versie leveren dezelfde bundels op;
- de **volledige** Leonardo-input blijft onder 35.000 tokens, dus inclusief vaste instructies,
  metadata en eventuele dossierstate;
- lokale bundels zijn afgeleide, disposable werkbestanden;
- verwerking en provenance worden in SQLite geregistreerd;
- geen bundel wordt automatisch naar GitHub teruggeschreven tijdens de observatiefase.

Het [dagelijkse runtimecontract](daily-runtime.md) legt bundelpaden, manifest,
SQLite-transacties, tokenizer, foutgedrag en concrete controlecommando’s vast.
De dagelijkse cronregel blijft voorlopig documentatie; eerst handmatig testen.
