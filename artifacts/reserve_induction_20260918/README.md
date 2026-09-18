# Schritt 3: Trennfamilien mit Quadrat-Reserven

Es gibt jetzt eine präzise stärkere Induktionsbedingung, ein bewiesenes
bedingtes Reparaturlemma und eine endliche Prüfung außerhalb der
Doppelleiter-Familie. **Eine allgemeine Erhaltung oder eine Lösung von
Conjecture 11.2 ist damit noch nicht bewiesen.**

## 1. Die zusätzliche Information

Sei H ein eingebetteter Barnette-Graph und Q eine quadratische Fläche mit
zyklischer Reihenfolge u,v,y,x. Schreibe a=uv, b=xy, c=ux, d=vy und
E_out=E(H)\E(Q). Die Orientierung bestimmt, welche gegenüberliegenden
Seiten a,b bei der Einfügung ersetzt werden.

Für eine Hamiltonkreisfamilie F heißt die markierte Reservebedingung:

    Für jedes f in E_out gibt es C in F mit c,d in C und f nicht in C.

Sie verlangt zwei gleichzeitig benutzte Kanten und eine vermiedene Kante.
Gewöhnliche Kanten-Trennung allein impliziert diese Bedingung nicht für
die gewählte Familie; das mittlere D(3,3)-Beispiel aus Schritt 2 zeigt das.

Ein **Reserve-Zertifikat (C,R)** besteht aus zwei disjunkten Familien von
Hamiltonkreisen. C trennt alle gerichteten Kantenpaare. C vereinigt R
erfüllt die Reservebedingung. Für mehrere mögliche nächste Einfügungen
fordern wir sie an jeder quadratischen Fläche in beiden Orientierungen.
Wir nennen diese stärkere Eigenschaft hier Quadrat-Robustheit.
Dies ist eine Arbeitsdefinition, keine Prioritätsbehauptung.

Die Reserve ist kein Teil der behaupteten hsep-Oberbescheinigung C.
Ihre Größe und der Aufwand, sie nach einem Schritt wieder bereitzustellen,
müssen aber separat kontrolliert werden. Alle Hamiltonkreise als Reserve
zu speichern wäre noch keine brauchbare quantitative Induktion.

## 2. Bedingtes Reserve-Reparaturlemma

Benutze genau die Quadrat-Einfügung aus Schritt 2: a wird durch u-p-q-v,
b durch x-r-s-y ersetzt, die neuen Sprossen sind pr und qs.
Sei C eine Trennfamilie mit k Kreisen und

    t = Anzahl der C-Kreise, deren Schnitt mit E(Q) genau {c,d} ist,
    Z = {f in E_out : kein C-Kreis enthält c,d und vermeidet f}.

Sei R_Q eine Familie von rho zusätzlichen alten Hamiltonkreisen, so dass
jede Kante f aus Z von mindestens einem R_Q-Kreis vermieden wird, der
zugleich c und d enthält. Dann besitzt der erweiterte Graph G eine
Trennfamilie mit höchstens

    k + 2t + rho

Kreisen. Nach dem zertifizierten gleichzeitigen Entfernen von delta Kreisen
bleibt eine Oberbescheinigung mit höchstens k+2t+rho-delta Kreisen.
rho bezeichnet eine tatsächlich vorgelegte Reservegröße; sie wird hier
nicht als minimal behauptet.

**Beweis.** Das Übertragungslemma aus Schritt 2 zeigt: Die Familie L aller
Fortsetzungen von C hat k+2t Kreise und lässt genau {pr,qs} × Z offen.
Jeder alte Kreis, der c und d enthält, besitzt eine Fortsetzung, die
**beide** neuen Sprossen pr und qs enthält. Dies folgt aus den drei möglichen
alten lokalen Überzügen {b,c,d}, {a,c,d} und {c,d} und der vollständigen
lokalen Tabelle. Die Fortsetzung behält sämtliche Außeninzidenzen bei.
Wähle für jeden nützlichen Reservekreis eine solche Fortsetzung. Ein Kreis,
der f vermeidet, erfüllt dadurch gleichzeitig (pr,f) und (qs,f).
Höchstens rho Fortsetzungen schließen somit alle Lücken. Das Streichkriterium
aus Schritt 1 erlaubt anschließend das Entfernen von delta Kreisen, sofern
die endgültig verbleibende Familie nachweislich alle Anforderungen erfüllt. ∎

Der neue Punkt ist die Schranke **ein Reparaturkreis je Reservezeuge**,
obwohl zwei neue Sprossen zu bedienen sind. Die Existenz der Reserve ist
eine ausdrückliche Voraussetzung des Lemmas.

## 3. Kandidat für die stärkere Induktionsaussage

Für n durch vier teilbar und n>=16 sei B(n)=floor(n(n+8)/32).
Der Start n=12 muss gesondert behandelt werden: B(12)=7, während die
bekannte Trennzahl dort 8 ist. Auf den anderen Restklassen wird hier keine
universelle B-Schranke behauptet.

Gesucht ist ein quantitativ kontrolliertes System von Reserve-Zertifikaten:

1. Jeder betrachtete n-Knoten-Graph besitzt (C,R) mit |C|<=B(n),
   Quadrat-Robustheit und einer noch zu bestimmenden Reservegrenze q(n).
2. Bei den für die Induktion benötigten zulässigen Einfügungen lassen sich
   C' und R' allein aus Fortsetzungen von C vereinigt R auswählen.
   C' trennt, C' vereinigt R' ist wieder quadrat-robust und |R'|<=q(n+4).
3. Mit s=B(n)-|C| gilt für die Reparatur und anschließende Reduktion

       2t + rho - delta <= B(n+4)-B(n) + s.

Die dritte Bedingung und das Lemma liefern |C'|<=B(n+4).
Die zweite Bedingung ist die entscheidende **Erhaltung der Zusatzinformation**.
Nur den ersten Schritt reparieren zu können, genügt nicht.

Dies ist ein präzises Beweisprogramm, noch kein Satz mit einer bewiesenen
Funktion q. Die Forderung für jedes Quadrat ist bequem, aber möglicherweise
stärker als nötig; eine strukturell begründete Auswahl geeigneter
Reduktionsstellen könnte ausreichen.

Auch ein Beweis dieses Programms für Quadrat-Einfügungen würde zunächst
nur die so erzeugte Graphklasse behandeln. Für Conjecture 11.2 fehlen
weiterhin eine vollständige Reduktionstheorie und die Gleichheitsanalyse
für die behauptete Eindeutigkeit des Extremalgraphen.

## 4. Endlicher Test und seine Grenzen

`inputs.json` übernimmt die 15 Census-Vertreter der nichtleeren Ordnungen
8,12,14,16,18,20 aus Release v0.9.0 sowie ihre expliziten Trennfamilien.
Die Anzahlen sind 1,1,1,2,2,8. Die Census-Vollständigkeit und die Auswahl
nichtisomorpher Vertreter beruhen auf diesem Release. Die Prüfung hier
verifiziert die einzelnen Graphen und **alle 206 markierten Einfügungen**;
die 206 Fälle sind keine 206 behaupteten Isomorphieklassen.

Mindestens acht Ausgangsgraphen liegen außerhalb aller D(a,b) mit positiven
ungeraden Parametern: die drei Vertreter der Ordnungen 14 und 18 sowie fünf
20-Knoten-Vertreter mit abweichendem Multiset der Flächenlängen. Als Vergleich
hat D(a,b) a+b quadratische Flächen, zwei Flächen der Länge a+3 und zwei der
Länge b+3. Gleiche Flächenmultisets werden nicht als Isomorphiebeweis verwendet.

Ergebnis für die konkret gespeicherten Familien:

- Alle 15 Ausgangsgraphen besitzen die verlangte Reserve. Die zusätzlich
  gewählten Familien haben zwischen null und sechs Kreise.
- In allen 206 Einfügungen ist die **gesamte fortgesetzte Familie C vereinigt R**
  an sämtlichen neuen Quadraten in beiden Orientierungen robust.
- Eine zusätzliche vollständige Zeugenprüfung bestätigt dies für diese
  206 markierten Graphen sogar für **jede** alte Familie, die sowohl trennt
  als auch quadrat-robust ist. Hier wird kein Größenbudget vorausgesetzt.
- Aus genau diesen Fortsetzungen werden neue Trennfamilien und neue
  Reserven gewählt. Kein neuer Kreis mit einem zuvor nicht gespeicherten
  Elternkreis wird dafür verwendet. Die neuen Reserven haben höchstens acht
  Kreise. Diese Zahl ist eine Beobachtung, keine allgemeine Reservegrenze.
- Bei allen 144 geprüften Übergängen 16->20 und 20->24 liegt die neue
  Trennfamilie innerhalb von B(20)=17 beziehungsweise B(24)=24.
- Im Fall `g03_f05_o1` behält das einfache Streichverfahren 18 Kreise.
  Eine begrenzte vollständige Suche unter den 20 verfügbaren Fortsetzungen
  findet eine trennende 17er-Auswahl. Das ist eine überprüfbare
  Oberbescheinigung, kein hier neu bewiesener exakter hsep-Wert.

Die quantitativen Resultate betreffen nur die ausgewählten Ausgangsfamilien.
Die größenunabhängige Erhaltung ist für alle zulässigen alten Familien
auf diesen festen Ausgangsgraphen überprüft. Daraus folgt kein Satz für
beliebige Graphen oder beliebig viele Schritte. Insbesondere wurden die neu
gewählten Familien nicht erneut als Eingabe einer zweiten Einfügungsrunde
getestet.

### Vollständiges Kriterium für die endliche Erhaltungsprüfung

Sei U das vollständige alte Kreisuniversum. Zu jeder alten Pflichtanforderung
r (gewöhnliches gerichtetes Kantenpaar oder Quadrat-Reserveanforderung)
sei S_r die Menge ihrer Zeugen in U. Für eine neue Reserveanforderung z sei
T_z die Menge alter Kreise, die mindestens eine z erfüllende Fortsetzung
haben. Dann gilt:

    Jede alte zulässige Familie erfüllt z nach voller Fortsetzung
    genau dann, wenn S_r eine Teilmenge von T_z ist für mindestens ein r.

**Beweis.** Bei S_r ⊆ T_z muss jede alte zulässige Familie S_r treffen und
trifft deshalb T_z. Gibt es kein solches r, enthält U\T_z mindestens einen
Zeugen jeder alten Pflichtanforderung. Diese gesamte Komplementfamilie ist
also zulässig, aber keine ihrer Fortsetzungen erfüllt z. ∎

Die vollständige Prüfung dieses Kriteriums für alle neuen Anforderungen
findet in allen 206 Fällen eine solche alte Pflichtanforderung. Sie ersetzt
damit die exponentielle Aufzählung sämtlicher Kreisfamilien. Der Erzeuger
benutzt Bitmengen, der unabhängige Prüfer explizite Mengen von Kreisindizes.
Dieses elementare Mengenargument ist keine Neuheitsbehauptung.

## 5. Reproduktion und unabhängige Kontrolle

```console
python -I artifacts/reserve_induction_20260918/verify.py
python -m pytest -q tests/test_reserve_induction.py
```

Diese Befehle prüfen das unveränderte Paket. Zur erneuten Erzeugung dient
`python artifacts/reserve_induction_20260918/analyze.py`. Ein Erzeugerlauf
schreibt neue Laufzeitmetadaten und ersetzt die erzeugten Audit-Dateien;
das Manifest beschreibt den hier geprüften Stand und muss für einen neuen
Stand nach dessen Prüfung neu erstellt werden.

Der Erzeuger verwendet die bisherige lokale Tabelle und eine vollständige
Pfadsuche für die alten Hamiltonkreise. Reserven werden deterministisch
greedy ausgewählt, ohne Minimalitätsanspruch. Die kleine Budgetsuche dient
nur dazu, eine zulässige Auswahl zu finden. Es gibt keinen Zufall und
keinen externen Optimierungslöser.

`verify.py` ist eine eigenständige Datei mit ausschließlich
Standardbibliothek-Imports. Die lokalen Basisprüfungen wurden aus dem
vorigen unabhängigen Quadrat-Prüfer übernommen; bestehende Module bleiben
unverändert. Der Prüfer enumeriert beide Kreisuniversen unabhängig über
perfekte Matchings, kontrolliert Planarität über Rotationen, Bipartitheit,
3-Zusammenhang, graph6, planar_code, sämtliche Trenn- und Reservezeugen,
die Herkunft aller ausgewählten Fortsetzungen und die Vollständigkeit der
markierten Quadratfälle. Hashes sind im Manifest festgehalten.

Die vollständigen Kreisuniversen dienen nur der endlichen unabhängigen
Kontrolle. Im Übergangszertifikat muss jede gewählte Familie tatsächlich
aus den zuvor gespeicherten Elternkreisen stammen.

`results.json` enthält Kommandos, Versionen, Laufzeit und Quellhashes;
`verification.json` protokolliert die unabhängige Prüfung.
Die gezielten Tests bestehen mit 234 Fällen; die vollständige Suite besteht
mit 831 Tests und zehn expliziten Auslassungen für externe Integrationen.
`review.json` hält diese Prüfläufe und die zugehörigen Quellhashes fest.
`--snapshot` am Erzeuger ist nur für das erneute Einlesen des lokalen
v0.9.0-Archivs nötig; die normalen Befehle benutzen die beiliegenden Eingaben.

## Nächster Beweisschritt

Zunächst ist die beobachtete Erhaltung der Quadrat-Robustheit strukturell
zu prüfen: Wie werden Reserveanforderungen an alten, benachbarten und neu
entstandenen Quadraten auf alte Anforderungen zurückgeführt? Erst danach
ist eine Reservegrenze mit dem scharfen Kreisbudget zu verbinden.
Der bedingte Reparatursatz kann separat verwendet werden; die globale
Erhaltung bleibt ausdrücklich ein Kandidat.
