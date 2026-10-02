# Architectuur

## Doel

Weekendkrant moet nieuws over meerdere interessegebieden gedurende de week verzamelen en daar uiteindelijk een leesbaar weekendmagazine van maken.

De architectuur probeert twee zaken tegelijk te optimaliseren:

- **kwaliteit**: bronnen bewaren, claims controleren, ruimte laten voor echte synthese;
- **kost**: dure modellen alleen inzetten waar hun intelligentie werkelijk nodig is.

## Hoofdflow

```text
Sherlock
  |
  | zoekt, triageert, vat bronnen compact samen
  v
GitHub: wekelijkse ingressbranch met bronfiches
  |
  v
Ariadne
  |
  | groepeert en vlecht deterministisch
  | volledige Leonardo-input <= 35k tokens
  v
Lokale thematische draad
  |
  v
Leonardo
  |
  | synthese, verbanden, narratief
  v
Concept
  |
  v
Striktland
  |
  | claimcontrole tegen aangeleverde bronnen
  +----------------------+
  | akkoord              | bezwaar
  v                      v
publiceerbaar          Minos
                         |
                         | gerichte herschrijving
                         v
                    publiceerbaar
```

## Scheiding tussen determinisme en intelligentie

Ariadne vormt de harde grens tussen de voorspelbare softwarelaag en de generatieve modellen.

Ariadne mag geen nieuws begrijpen, waarderen of samenvatten. Haar taken moeten reproduceerbaar zijn:

- nieuwe bestanden ophalen;
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

GitHub is tijdens de observatiefase de gedeelde bron van waarheid voor:

- code en ontwerpdocumentatie;
- Sherlocks wekelijkse bronfiches op `ingress/<ISO-jaar>_W<week>`;
- later, waar nuttig, dossiers en uiteindelijke publicatieartefacten.

Ariadnes afgeleide draden zijn in deze fase **geen** permanente repository-artefacten.
Ze worden lokaal opgebouwd, mogen opnieuw gegenereerd worden en hoeven niet naar
GitHub gepusht te worden. Zo kan het bundelcontract nog wijzigen zonder de repository
met tijdelijke tussenproducten te vullen.

De lokale verwerkingsaudit wordt in SQLite bijgehouden. Die database registreert
onder meer welke ingressfiches in welke draad terechtkwamen en welke verwerkingsstap
werd uitgevoerd. De database is operationele staat, geen vervanging voor de
versioneerbare bronfiches op GitHub.

Het vaste pad voor Ariadnes SQLite-verwerkingsdatabase op `bibib` is
`/home/weekendkrant/weekendkrant.sqlite3`. De runtime-indeling is:

| Pad | Inhoud |
| --- | --- |
| `/home/weekendkrant/app/` | Git-repository met versieerbare code, tests en documentatie, plus de lokale `.venv`. |
| `/home/weekendkrant/logs/` | Roterende diagnostische runtime-logs, waaronder `ariadne.log`. |
| `/home/weekendkrant/weekendkrant.sqlite3` | Ariadnes persistente lokale verwerkingsstaat. |

De database staat bewust buiten de Git-working tree en wordt niet naar GitHub
gecommit. Ze is geen logbestand en hoort daarom ook niet onder `logs/`.
Het concrete schema staat in de auditdocumentatie; lokale draden staan onder
`/home/weekendkrant/draden/`.

De Raspberry Pi voert weekvoorbereiding en dagelijkse verwerking als afzonderlijke
deterministische taken uit. Beide taken zijn geïmplementeerd; zie het [dagelijkse runtimecontract](daily-runtime.md).

## Dagafsluiting en dagelijkse uitvoering (afgesproken ontwerp)

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

Zodra de geldige gereedmelding beschikbaar is, synchroniseert Ariadne de weekbranch
veilig via fast-forward en verwerkt ze de afgesloten dagoogst. Een reeds succesvol
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
zie [de operationele dagstatus](audit-trail.md#operationele-dagstatus-afgesproken-ontwerp).

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
nooit het aanmaken en pushen van de volgende weekbranch. De foutstatus blijft
bewaard en wordt niet als opgelost gemarkeerd. Gewone Git- en runtimefouten blijven
wel redenen om veilig te stoppen.

Bij een ontbrekende gereedmelding kan Sherlock nog op de oude weekbranch schrijven.
Ariadne mag daarom geen afsluitende wijzigingen aan die branch forceren, oogst
overschrijven of de branch verwijderen. De nieuwe week voorbereiden is geen bewijs
dat de oude oogst compleet is.

Na de weekovergang gaat de dagelijkse Ariadne uitsluitend verder met de nieuwe
actuele week. Er is **geen inhaalverwerking van vorige weken**: eventuele late
aanvullingen blijven op de oude branch staan en de fout blijft geregistreerd.

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

Het subcommand `prepare-week` bereidt Sherlocks werkruimte voor. Het vaste technische
padcontract is `ingress/<ISO-jaar>_W<week>/` op branch
`ingress/<ISO-jaar>_W<week>` (twee cijfers voor de week).
Een `.gitkeep` maakt de lege map versieerbaar. Dit legt het inhoudelijke
bronfichecontract niet vast: dat blijft onderdeel van de observatiefase.

De stap hergebruikt bestaande weekbranches en overschrijft geen oogst of auditrecord.
Het voorbereidingsrecord bewaart het uitgangscommit; het JSON-schema blijft ongewijzigd.
Het subcommand `prepare-week` voert de wekelijkse Git-workflow zelfstandig uit:
schone werkboom controleren, `fetch origin`, `main` uitsluitend fast-forward gelijk
maken aan `origin/main`, weekbranch selecteren/aanmaken, voorbereiding valideren,
alleen `.gitkeep` en het week-auditrecord committen indien nodig, en de weekbranch
naar `origin` pushen met upstream. Een nieuwe branch start op de bijgewerkte `main`.

Bestaande lokale weekhistory krijgt voorrang; bij een alleen remote bestaande
weekbranch wordt een lokale trackingbranch gemaakt. Bestaande oogst blijft intact.
Een weekremote die vooruitloopt of divergeert, lokaal vooruitgelopen/divergente
`main`, een vuile werkboom of conflicterende metadata leidt tot veilig stoppen.
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
