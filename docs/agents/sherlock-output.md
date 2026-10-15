# Sherlock-outputcontract, versie 1

De persistente Sherlock-run is het resultaatartifact. De backend levert de exacte
`sherlock-run:<run_id>` als `result_ref`. Geef bij generieke finish uitsluitend die
referentie mee als `output_refs`, ook bij een lege oogst. De backend sluit run en
attempt in dezelfde transactie. Bronregistraties en fiches blijven via run_id
gekoppeld aan job_id en attempt_id. Claimgegevens zijn transportmetadata, geen
fiche-inhoud. Bevestigde bronregistraties en fiches worden bij fouten behouden.

`succeeded` vereist inhoudelijk voltooide zoekdekking, alle werkelijk gereviewde
bronnen geregistreerd en alle geselecteerde fiches bevestigd. `failed` sluit een
bekend mislukte uitvoering af. Bij onzekere effecten gebruik `uncertain` of
abandon; de job blijft geblokkeerd voor expliciet operatorherstel. Een finishreceipt
bewijst registratie van de uitkomst, geen inhoudelijke verificatie van de scout.
