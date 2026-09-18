# Schritt 2: Eine konkrete Quadratreduktion und ihre genaue Übertragungslücke

**Ergebnis:** Für das Ersetzen einer quadratischen Fläche durch einen
Leiterstreifen aus drei Quadraten lässt sich die Kreisübertragung vollständig
beschreiben. Alle Randzustände bleiben erhalten. Bei einer gegebenen
Trennfamilie können nach dem Mitnehmen aller lokalen Fortsetzungen jedoch
Trennanforderungen fehlen. Wir charakterisieren diese Anforderungen exakt.
Am mittleren Quadrat von D(3,3) schließt ein zusätzlicher Kreis die Lücke:
**12 alte Kreise → 16 Fortsetzungen → 17 trennende Kreise auf 20 Knoten.**

Dies ist ein Beweisentwurf für eine bestimmte Reduktionsregel mit endlichen
Kontrollen. Weder ihre Anwendbarkeit auf alle Barnette-Graphen noch ein
allgemeines scharfes Induktionsbudget ist damit bewiesen.

## 1. Die Operation und eine präzise Zulässigkeitsbedingung

Sei H ein Barnette-Graph mit einer quadratischen Fläche in der Reihenfolge
`u,v,y,x`. Ihre Kanten heißen

    a=uv, b=xy, c=ux, d=vy.

Ersetze a durch `u-p-q-v` und b durch `x-r-s-y`; füge `pr` und `qs` hinzu.
Die Kanten c und d bleiben. Das Ergebnis G hat vier zusätzliche Knoten;
der alte quadratische Teilgraph wird zu einem Leiterstreifen mit vier Spalten
und drei quadratischen Zellen. Die vier äußeren Anschlüsse liegen weiterhin
an u,v,x,y. Die Erhaltung der Barnette-Eigenschaften in dieser Richtung ist
bereits im Hauptmanuskript bewiesen.

Die allgemeinere C4-Expansion ist etablierte Literatur. Unsere Regel
beschränkt sich auf gegenüberliegende Kanten **einer quadratischen Fläche**;
die dort beschriebenen allgemeineren Expansionen auf längeren Flächen sind
nicht von den nachstehenden Übertragungsaussagen erfasst. Siehe
[Gorsky, Steiner und Wiederrecht, Abschnitt 5](https://arxiv.org/html/2202.11641),
insbesondere Definition und Theorem 5.1. Es wird keine Neuheit der Operation
beansprucht.

**Reduktionskriterium.** Angenommen, G ist ein Barnette-Graph und enthält
einen induzierten Acht-Knoten-Leiterstreifen in genau dieser Anordnung.
Seine drei quadratischen Zellen müssen ein flächiges Scheibengebiet bilden.
Die inneren Knoten p,q,r,s haben keine weiteren Nachbarn; die vier Ecken
u,v,x,y haben jeweils ihren dritten Nachbarn außerhalb des Streifens.
Entferne p,q,r,s und ergänze uv und xy. Dann ist der reduzierte Graph H
genau dann ein Barnette-Graph, wenn beide Graphen

    H − {u,y}   und   H − {v,x}

zusammenhängend sind.

**Beweis.** Einfachheit folgt aus dem induzierten Streifen und den
verschiedenen Ecken; die neuen Kanten waren vorher nicht vorhanden.
Die Grade werden drei. Die ersetzten Wege haben Länge drei, also liegen
ihre Endpunkte in verschiedenen Bipartitionsklassen. Die neuen Kanten
können im Scheibengebiet eingezeichnet werden; H ist planar und bipartit.

Für den Zusammenhang nach Entfernen einer Menge S von höchstens zwei
H-Knoten benutzen wir den Zusammenhang von G−S. Außer wenn S aus zwei
gegenüberliegenden Ecken besteht, sind die verbleibenden Ecken im alten
Quadrat verbunden. Jeder Teil eines G−S-Weges durch den inneren Streifen
lässt sich dann durch einen Weg im Quadrat von H−S ersetzen. Folglich
ist H−S verbunden. Es verbleiben genau die beiden im Kriterium genannten
Diagonalen. Ihre Überprüfung ist daher hinreichend und wegen der Definition
von 3-Zusammenhang auch notwendig. Dieses Kriterium behauptet nicht, dass
jeder Barnette-Graph einen solchen Streifen besitzt. ∎

## 2. Vollständige lokale Zustandstabelle

Ein Hamiltonkreis beschränkt sich auf das Quadrat beziehungsweise den
Streifen als spannender, zyklenfreier Pfadüberzug. S bezeichnet die Ecken,
deren äußere Anschlusskante benutzt wird. Bei zwei Anschlüssen liegt ein
Spannpfad vor; bei vier Anschlüssen sind es zwei Pfade mit der angegebenen
Paarung. Die Ecke u entspricht Index 0, v Index 1, x Index 2 und y Index 3
in den maschinenlesbaren Zertifikaten.

| Zustand | Alter Pfadüberzug | Neuer Pfadüberzug / neue Pfadüberzüge |
|---|---|---|
| S={u,v} | b,c,d | c,pq,pr,qs,xr,sy,d |
| S={u,x} | a,b,d | up,pq,qv,d,xr,rs,sy |
| S={v,y} | a,b,c | up,c,pq,qv,xr,rs,sy |
| S={x,y} | a,c,d | up,c,pr,qv,qs,d,rs |
| S=alle, Paarung uv\|xy | a,b | up,pq,qv,xr,rs,sy |
| S=alle, Paarung ux\|vy | c,d | up,pq,qs,d,xr,rs |
| derselbe Zustand | c,d | up,pr,qv,qs,xr,sy |
| derselbe Zustand | c,d | c,pq,pr,qv,rs,sy |

Die Tabelle folgt durch die Gradbedingungen: benutzte Anschlüsse haben
intern Grad eins, alle anderen Knoten Grad zwei; geschlossene Komponenten
sind ausgeschlossen. Im Quadrat bleiben vier Spannpfade und zwei
Zweipfadüberzüge. Im Streifen ergeben dieselben Fälle die acht aufgeführten
Überzüge. Die Tests prüfen die Vollständigkeit zusätzlich gegen sämtliche
Kantenteilmengen der möglichen Größen mit einem unabhängigen Pfadprüfer.

**Folgerung.** Jeder alte Hamiltonkreis besitzt genau eine Fortsetzung,
außer beim lokalen Überzug {c,d}, der genau drei Fortsetzungen besitzt.
Alle Fortsetzungen behalten sämtliche Kanten außerhalb des Quadrats sowie
die Paarung der Randanschlüsse unverändert bei und sind deshalb Hamiltonkreise.
Umgekehrt projiziert jeder neue Hamiltonkreis eindeutig auf einen alten:
Die sechs Zustände stimmen überein und der alte Überzug ist je Zustand eindeutig.

Für eine alte Familie C mit k Kreisen und

    t = Anzahl ihrer Kreise mit lokalem Überzug genau {c,d}

hat die Familie L **aller** Fortsetzungen somit genau `k+2t` Kreise.
Diese Zahl allein garantiert noch keine vollständige Trennung.

## 3. Exakte Charakterisierung der fehlenden Trennanforderungen

Sei C eine Hamiltonsche Kanten-Trennfamilie in H. Sei E_out die Menge aller
H-Kanten außerhalb des Quadrats; dazu gehören auch die vier Anschlusskanten.
Definiere

    Z(C) = { f in E_out : kein Kreis in C enthält c und d und vermeidet f }.

**Übertragungslemma.** In L, der Familie aller lokalen Fortsetzungen von C,
fehlen genau die gerichteten Anforderungen

    {pr,qs} × Z(C).

Insbesondere ist L genau dann kanten-trennend, wenn Z(C) leer ist. Andernfalls
fehlen genau `2|Z(C)|` Anforderungen. Hier geht es um die konkret gewählte
Familie C, nicht notwendigerweise um alle Hamiltonkreise von H.

**Beweis.** Zunächst kommt jeder der sechs alten Zustände in C vor.
Für die vier Zweianschlusszustände erzwingen die Anforderungen `(b,a)`,
`(d,c)`, `(c,d)` und `(a,b)` jeweils den betreffenden Zustand. Schreibt
man t_x für die äußere Anschlusskante an x, so erzwingen `(t_x,d)` und
`(t_x,a)` die beiden Vieranschlusszustände. Dies lässt sich direkt an
den sechs alten Überzügen und ihren Anschlussmengen ablesen.

Daher kommen in L alle acht neuen lokalen Überzüge vor. Ihre lokalen
Inzidenzen einschließlich der vier Anschlusskanten trennen sämtliche
Kantenpaare innerhalb dieses erweiterten lokalen Bereichs, wie die obige
Tabelle zeigt. Paare aus zwei E_out-Kanten bleiben durch die unveränderten
Außeninzidenzen getrennt.

Für Paare aus einer neuen inneren und einer E_out-Kante dient folgende
Tabelle als Zeugenübertragung. Bei jeder aufgelisteten neuen Kante kann
sowohl Benutzung als auch Vermeidung der angegebenen alten Kante durch
eine Fortsetzung mit derselben Benutzung beziehungsweise Vermeidung der
neuen Kante realisiert werden:

| Neue Kante | Alte Zeugen-Kante |
|---|---|
| up, qv, rs | a |
| pq, xr, sy | b |
| c | c |
| d | d |

Weil die alte Zeugen-Kante im Quadrat liegt, ist sie von der Außenkante
verschieden. Die Trenneigenschaft von C liefert daher beide benötigten
gerichteten Zeugen.

Für die beiden inneren Sprossen pr und qs gilt laut Zustandstabelle:
Eine Fortsetzung, die die betreffende Sprosse enthält, existiert genau dann,
wenn der alte Kreis **beide** Kanten c und d enthält. Deshalb ist
`(pr,f)` beziehungsweise `(qs,f)` genau für f aus Z(C) nicht erfüllbar.
Die umgekehrte Richtung `(f,pr)` und `(f,qs)` ist immer erfüllbar:
Ein alter Zeuge für `(f,c)` vermeidet c; sein Zustand besitzt eine
Fortsetzung, welche die betreffende neue Sprosse vermeidet. Damit sind
alle möglichen Kantenpaar-Typen behandelt. ∎

**Bedeutung.** Das gewöhnliche hsep-Zertifikat enthält Zeugen für eine
benutzte und eine vermiedene Kante. Die Fortsetzung kann aber Zeugen für
**zwei gleichzeitig benutzte Kanten und eine vermiedene Außenkante** benötigen.
Ein bloßes Profil der Anzahlen pro Zustand enthält diese Information nicht.

## 4. Das mittlere Quadrat von D(3,3)

Im Fall `examples/D33_f01_o0.json` ist das Quadrat

    u=1, v=2, y=6, x=5.

Die neuen Knoten sind p=16,q=17,r=18,s=19. Die in Schritt 1 eindeutig
bestimmte optimale 12er-Familie besitzt t=2. Ihre 16 Fortsetzungen lassen
genau folgende Anforderungen offen:

    ((16,18),(9,10))       ((16,18),(13,14))
    ((17,19),(9,10))       ((17,19),(13,14)).

Ein einziger zusätzlicher Hamiltonkreis enthält beide neuen inneren
Sprossen und vermeidet beide genannten Außenkanten. Der unabhängige Prüfer
kontrolliert seine Hamiltonizität und sämtliche 870 gerichteten Anforderungen
des 30-Kanten-Graphen. So entsteht eine **17er-Oberbescheinigung**, passend zu
`B(20)=17`. Die Minimalität des zusätzlichen Reparaturaufwands für diese
festen 16 Fortsetzungen ist unmittelbar zertifiziert: Ohne einen weiteren
Kreis fehlen Anforderungen, mit einem weiteren sind alle erfüllt.
Ein neuer exakter hsep-Wert des Zielgraphen wird hier nicht beansprucht.

Der Reparaturkreis projiziert auf Kreis **6** aus dem Zertifikat von Schritt 1.
Dieser gehörte ausdrücklich **nicht** zur optimalen alten 12er-Familie.
Damit reicht es in diesem Beispiel nicht, nur die aktuell ausgewählten Kreise
fortzuführen. Genau der zuvor entbehrliche Kreis wird als Reserve nützlich.
Das All-Rails-Argument aus Schritt 1 war korrekt; eine für den aktuellen
Graphen redundante Auswahl muss jedoch nicht für spätere Einfügungen ausreichen.

## 5. Budget und offener struktureller Schritt

Wenn nach der vollständigen Fortsetzung r Reparaturkreise hinzukommen und
d Kreise aus der Gesamtfamilie mit geprüfter Erhaltung aller Anforderungen
gestrichen werden, lautet die zertifizierte Obergrenze

    k + 2t + r − d.

Mit `s=B(n)−k >= 0` genügt für den Schritt von n auf n+4 daher

    2t + r − d <= B(n+4) − B(n) + s.

Im mittleren Doppelleiter-Beispiel gilt `t=2,r=1,d=0,s=0`, also genau
`4+1=17−12`. Bei den entsprechenden Randquadraten genügen zunächst 18
Fortsetzungen, von denen anschließend ein redundanter Kreis gestrichen wird.

Für eine allgemeine Induktion ist eine **Trennfamilie mit zusätzlichen
Reservezeugen** ein konkreter Kandidat für die stärkere Induktionsinformation.
Das bloße Speichern einer optimalen Trennfamilie garantiert die nötige
gemeinsame Kantenbenutzung nicht. Offen bleiben insbesondere:

1. Eine zulässige Reduktion muss für die gesamte interessierende Graphklasse
   gefunden werden; das Vorhandensein eines Drei-Quadrate-Streifens ist
   hier eine Voraussetzung, keine allgemeine Schlussfolgerung.
2. Die benötigten Reservezeugen müssen existieren und bei weiteren Schritten
   in einer kontrollierten Form verfügbar bleiben.
3. Die obige Budgetung muss allgemein bewiesen werden; die lokalen
   Zustandstabellen allein geben noch keine passende Schranke für r oder d.
4. Die Eindeutigkeit der Extremalgraphen verlangt weiterhin eine zusätzliche
   Analyse der Gleichheitsfälle.

Die Würfeleinfügung und allgemeinere C4-Expansionen bleiben für eine
vollständige Reduktionstheorie relevant; deren bekannte Erzeugungssätze
liefern nicht automatisch die hier benötigten quantitativen Trennzeugen.

## 6. Prüfung und Reproduktion

Es wurden nur 36 beschriftete Einfügungen untersucht: alle quadratischen
Flächen und beide Orientierungen beim Würfel, beim Sechseckprisma und
beim festen 16-Knoten-Beispiel D(3,3). Die Zielgraphen haben höchstens
20 Knoten. Es handelt sich nicht um 36 behauptete Isomorphieklassen und
nicht um einen neuen Graphenkatalog.

- Bei 34 Fällen trennen bereits sämtliche Fortsetzungen der ausgewählten
  Ausgangsfamilie alle Kantenpaare.
- In zwei mittleren Doppelleiter-Fällen fehlen je vier Anforderungen;
  jeweils ein zusätzlicher Kreis schließt die Lücke.
- Nach geprüftem Entfernen redundanter Kreise erfüllen alle zwölf
  D(3,3)-Einfügungen die Obergrenze 17. Kleinere gefundene Obergrenzen
  werden nicht als exakte Werte ausgegeben.
- Der Würfel führt zu 12-Knoten-Graphen mit Obergrenze 8. Die Formel B
  ist dort keine gültige universelle Schranke (`B(12)=7`); diese Fälle
  prüfen die lokale Operation, nicht den Induktionsstart für Conjecture 11.2.

```console
python artifacts/square_reduction_20260918/analyze.py
python -I artifacts/square_reduction_20260918/verify.py artifacts/square_reduction_20260918/examples/D33_f01_o0.json
python -m pytest -q tests/test_square_reduction.py
```

Der Erzeuger enumeriert alte Kreise durch vollständige Pfadsuche und bildet
neue Kreise durch die lokale Tabelle. Er benutzt NetworkX für Einbettungen.
Der neue eigenständige Prüfer importiert nur die Python-Standardbibliothek:
Er kontrolliert bipartite Färbbarkeit, alle Löschungen von bis zu zwei Knoten,
planare Rotationssysteme mittels Flächenumlauf und Euler-Charakteristik,
die Operation, graph6, und beide vollständigen Kreisuniversen unabhängig
über Komplemente perfekter Matchings. Alle behaupteten Trennungen und
alle vier fehlenden Anforderungen werden direkt geprüft.

Die 47 neuen Tests enthalten zusätzlich vollständige lokale Fallprüfungen,
das Kanten-Zeugen-Schema und negative Kontrollen. `results.json`,
`review.json` und `SHA256SUMS.txt` enthalten Kommandos, Versionen, Laufzeiten
und Hashes. Es gibt keine Zufallsentscheidungen, keinen externen
Optimierungslöser und keinen Anspruch auf optimale Greedy-Auswahl.
Die bestehenden Solver und Prüfer wurden nicht geändert. Die große
Nachberechnung bleibt pausiert.

Die Aussagen sind ein intern geprüfter Beweisentwurf, keine externe
Begutachtung, keine Prioritätsbehauptung und kein Beweis von Conjecture 11.2.
