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
