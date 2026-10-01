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

De Raspberry Pi kan Ariadne via cron uitvoeren. Weekvoorbereiding en verwerking zijn
afzonderlijke deterministische taken; het exacte cronritme wordt pas vastgelegd nadat
de observatiefase voldoende praktijkgegevens heeft opgeleverd.

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

`ariadne.py` bereidt uitsluitend Sherlocks werkruimte voor. Het vaste technische
padcontract is `ingress/<ISO-jaar>_W<week>/` op branch
`ingress/<ISO-jaar>_W<week>` (twee cijfers voor de week).
Een `.gitkeep` maakt de lege map versieerbaar. Dit legt het inhoudelijke
bronfichecontract niet vast: dat blijft onderdeel van de observatiefase.

De stap hergebruikt bestaande weekbranches en overschrijft geen oogst of auditrecord.
Het voorbereidingsrecord bewaart het uitgangscommit. Git-commit en push gebeuren
apart, na inspectie. Synchronisatie, fichevalidatie, verwerkingstatus, bundeling,
tokenmeting en redactionele modelcalls vallen buiten deze eerste implementatie.

## Volgende Ariadne-fase: lokale bundeling

De volgende deterministische stap mag Sherlocks bestaande ingress lezen en daar
lokale Leonardo-inputs van maken. Daarbij gelden voorlopig deze invarianten:

- bundelen gebeurt mechanisch op basis van expliciete metadata, niet op semantische interpretatie;
- dezelfde input en dezelfde Ariadne-versie leveren dezelfde bundels op;
- de **volledige** Leonardo-input blijft onder 35.000 tokens, dus inclusief vaste instructies,
  metadata en eventuele dossierstate;
- lokale bundels zijn afgeleide, disposable werkbestanden;
- verwerking en provenance worden in SQLite geregistreerd;
- geen bundel wordt automatisch naar GitHub teruggeschreven tijdens de observatiefase.

Het precieze lokale pad, databaseschema en cronritme blijven implementatiedetails
totdat ze in een afzonderlijke, testbare stap worden vastgelegd.
