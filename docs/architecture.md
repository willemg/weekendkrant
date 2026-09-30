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
GitHub: verzamelde nieuwsitems
  |
  v
Ariadne
  |
  | groepeert en vlecht deterministisch
  | volledige Leonardo-input <= 35k tokens
  v
Thematische draad
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

## GitHub als centrale werkruimte

GitHub dient als:

- overdrachtspunt tussen Sherlock en Ariadne;
- versieerbaar archief van bronfiches en draden;
- opslagplaats voor dossiers en uiteindelijke artikels;
- audit trail van wijzigingen;
- menselijk inspecteerbare bron van waarheid.

De Raspberry Pi kan Ariadne via cron uitvoeren, maar GitHub blijft de gedeelde werkruimte.

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
