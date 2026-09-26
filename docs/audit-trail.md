# Audit trail en kwaliteitslabels

## Doel

De krant moet intern kunnen reconstrueren hoe een relevante feitelijke claim tot stand kwam.

Daarom krijgt iedere claim provenance: welke bronfiches eraan gekoppeld waren, welk model ze schreef, welke controle erop gebeurde en of een herschrijving nodig was.

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
