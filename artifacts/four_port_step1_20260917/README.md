# Schritt 1: Warum 13 Kreise entstehen und wie wir 12 erreichen

Die vier untersuchten 16-Knoten-Beispiele besitzen jeweils eine unabhängig
zertifizierte 12er-Trennfamilie. Zwölf private Kantenpaar-Anforderungen beweisen
zugleich die untere Schranke. Damit gilt **hsep = 12**. Alle vier Beispiele
sind beschriftete Darstellungen **derselben Isomorphieklasse D(3,3)**.
Explizite Isomorphismen liegen in den Zertifikaten; es sind keine vier neuen Graphen.

## Die entscheidende Diagnose

Die 14 Hamiltonkreise verteilen sich auf sechs kompatible Zustandsblöcke:

| Blocktyp | Vollständige Familie | Bisherige Auswahl | Optimale Familie |
|---|---:|---:|---:|
| Vier Blöcke mit zwei benutzten Anschlüssen | 4 | 4 | 4 |
| Ein Block mit vier Anschlüssen und je einem lokalen Pfadüberzug | 1 | 1 | **0** |
| Ein Block mit vier Anschlüssen und 3 × 3 Pfadüberzügen | 9 | 8 | 8 |
| **Gesamt** | **14** | **13** | **12** |

Der zusätzliche Kreis ist der All-Rails-Kreis: Er verwendet beide Leiterholme
auf jeder Seite sowie alle vier Verbindungskanten. Er ist der einzige Kreis
seines kompatiblen Zustandsblocks. Das bisherige Lemma behält ihn deshalb
zwangsläufig bei. Seine sämtlichen 128 gerichteten Trennanforderungen werden
jedoch bereits von den anderen zwölf ausgewählten Kreisen erfüllt.

Im 3 × 3-Block genügt das Weglassen des mittleren Kreises. Jeder lokale
Pfadüberzug dieses Blocks hat sechs Kanten; die Vereinigung der drei Überzüge
hat zehn Kanten. Ein einzelner Überzug kann sie nicht überdecken, zwei können
es. Somit sind die kleinsten lokalen Vereinigungsüberdeckungen p = q = 2.
Der bisherige Ansatz benötigt in diesem Block mindestens

    p*b + a*q - p*q = 2*3 + 3*2 - 2*2 = 8

Kreise. Zusammen mit den fünf verpflichtend beibehaltenen Einzelblöcken ergibt
das **mindestens 13**. Das ist eine nachgewiesene Grenze dieser Konstruktion
auf den unveränderten vollständigen Zustandsfamilien, kein Greedy-Artefakt.
Sie ist keine Grenze jedes Verfahrens mit Randzuständen.

## Konkrete Kreise und Beweise

Die Indizes sind nullbasiert und beziehen sich auf `cycles` in jedem Zertifikat.

- Alle Hamiltonkreise: `0,...,13`.
- Bisher weggelassen: `6`.
- Zusätzlich wegzulassen: `1` (der ganze Einzelblock).
- Die zwölf ausgewählten Kreise sind `0,2,3,4,5,7,8,9,10,11,12,13`.
- Zu jedem ausgewählten Kreis ist ein gerichtetes Kantenpaar gespeichert,
  das unter **allen 14 Hamiltonkreisen nur dieser Kreis** trennt.

Die letzte Eigenschaft erzwingt alle zwölf Kreise in jeder Trennfamilie.
Sie beweist sowohl die untere Schranke 12 als auch die Eindeutigkeit der
minimalen Kreisfamilie auf dem jeweiligen beschrifteten Graphen. Daraus folgt
keine neue Aussage zur Eindeutigkeit extremaler Graphen beliebiger Ordnung.

Für `certificate_02.json` decken bereits die sieben ausgewählten Kreise
`0,2,3,7,8,10,11` alle Anforderungen des entfernten All-Rails-Kreises `1` ab.
Die vier Kreise `3,5,7,9` decken alle Anforderungen des ebenfalls entfernten
Kreises `6` ab. Die Zertifikate prüfen diese Zeugen **nach dem gleichzeitigen
Entfernen beider Kreise**. Minimalität dieser Ersatz-Zeugenmengen wird hier
nicht als eigenständiges Ergebnis beansprucht.

## Konsequenz für die nächste Induktionsaussage

Die Forderung, jeden lokalen Pfadüberzug oder jeden kompatiblen Zustandsblock
weiterhin zu repräsentieren, ist schon für D(3,3) zu stark. Die benötigte
Information betrifft die Trennanforderungen **über die Zustandsblöcke hinweg**.

Eine sichere Ergänzung des bisherigen Lemmas ist das folgende einfache
Streichkriterium. Für jede Kreisfamilie F sei

    Req(F) = {(e,f) : ein Kreis in F enthält e und vermeidet f}.

Sei K eine konstruierte Familie und R eine Teilfamilie, die bleiben soll.
Falls für jeden entfernten Kreis C gilt

    Req({C}) ⊆ Req(R),

dann ist `Req(K) = Req(R)`. Beweis: Die Anforderungen von K sind genau die
Vereinigung der Anforderungen aller seiner Kreise; jede entfernte Teilmenge
liegt nach Voraussetzung bereits in der Vereinigung der verbleibenden.
Die Voraussetzung muss für die **endgültig verbleibende** Familie gelten.
Einzelne Löschbarkeit mehrerer Kreise erlaubt im Allgemeinen noch nicht ihre
gleichzeitige Löschung.

Dieses Kriterium kann ganze Zustandsblöcke entfernen und schließt die Lücke
13 → 12 im untersuchten Beispiel. Es ist ein elementares Kriterium zur
Prüfung eines Zertifikats, noch keine strukturelle Schranke für alle Graphen.
Für eine allgemeine Induktion müsste nun nachgewiesen werden, wann die nötigen
blockübergreifenden Zeugen immer existieren und innerhalb des Budgets bleiben.
Diese Muster an den nächsten kleinen Familienmitgliedern zu untersuchen ist
der folgerichtige nächste begrenzte Versuch. Er wurde hier nicht vorweggenommen.

## Reproduktion und unabhängige Prüfung

```console
python artifacts/four_port_step1_20260917/analyze.py
python -I artifacts/four_port_step1_20260917/verify.py artifacts/four_port_step1_20260917/certificate_02.json artifacts/four_port_step1_20260917/certificate_10.json artifacts/four_port_step1_20260917/certificate_13.json artifacts/four_port_step1_20260917/certificate_21.json
python -m pytest -q tests/test_four_port_step1.py
```

Der Erzeuger liest ausschließlich die vier bereits vorhandenen kleinen
Beispiele. NetworkX wird nur für die Ermittlung der expliziten Isomorphismen
benutzt. Der neue Verifikator verwendet ausschließlich die Python-Standardbibliothek
und importiert keinen Erzeuger oder vorhandenen Projektverifikator.
Er enumeriert unabhängig alle Hamiltonkreise durch vollständige Pfadsuche,
prüft alle 552 gerichteten Kantenpaare, die zwölf unteren Zeugen, graph6,
die Isomorphismen, die Zustandsblöcke und ihre lokalen Überdeckungsminima.

`analysis.json` protokolliert Versionen, Laufzeit, Kommando und Hashes.
`review.json` und `SHA256SUMS.txt` dokumentieren die abschließende Prüfung.
Es gibt keine Zufallsentscheidungen und keinen externen Optimierungslöser.
Bestehende Solver und Verifikatoren wurden nicht geändert; die große
Nachberechnung der verlorenen Zertifikate bleibt pausiert.
