#!/usr/bin/env python3
"""Standalone standard-library verifier for Barnie-sequence artifacts."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Iterable, Iterator, Sequence


ORDERS = tuple(range(8, 37))
REFERENCE_COUNTS = {8:1,10:0,12:1,14:1,16:2,18:2,20:8,22:8,24:32,26:57,28:185,30:466,32:1543,34:4583,36:15374}
BARNIE_HASH = "2f96ada16c46cd2bd038b97d5af44f46ed14522cba1edf3fa041d66e02107bcc"
HEADER = b">>planar_code<<"
GRAPH_SCHEMA = "barnie-sequence-graph-v1"
COVER_SCHEMA = "barnie-sequence-cover-v1"
EXACT_SCHEMA = "barnie-sequence-exact-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_canonical_gzip(path: Path) -> tuple[list[dict[str, Any]], str, int]:
    raw = path.read_bytes()
    if len(raw) < 10 or raw[:2] != b"\x1f\x8b" or raw[4:8] != b"\0\0\0\0":
        raise ValueError(f"gzip is absent or has a nonzero timestamp: {path.name}")
    digest = sha256()
    size = 0
    values = []
    with gzip.open(path, "rt", encoding="ascii", newline="") as source:
        for number, line in enumerate(source, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"non-terminated JSONL line {number}: {path.name}")
            value = json.loads(line)
            if canonical_json(value) + "\n" != line:
                raise ValueError(f"noncanonical JSONL line {number}: {path.name}")
            data = line.encode("ascii")
            digest.update(data); size += len(data); values.append(value)
    return values, digest.hexdigest(), size


def parse_planar_code(data: bytes) -> tuple[tuple[int, ...], ...]:
    if not data.startswith(HEADER):
        raise ValueError("missing planar_code header")
    position = len(HEADER)
    if position >= len(data):
        raise ValueError("empty planar_code")
    order = data[position]; position += 1
    if order == 0:
        raise ValueError("zero planar_code order")
    rows = []
    for _ in range(order):
        row = []
        while True:
            if position >= len(data):
                raise ValueError("truncated planar_code")
            value = data[position]; position += 1
            if value == 0: break
            if value > order: raise ValueError("planar_code neighbor out of range")
            row.append(value - 1)
        rows.append(tuple(row))
    if position != len(data):
        raise ValueError("trailing planar_code data")
    rotation = tuple(rows)
    for vertex, row in enumerate(rotation):
        if vertex in row or len(row) != len(set(row)) or any(vertex not in rotation[n] for n in row):
            raise ValueError("planar_code is not a simple symmetric graph")
    return rotation


def edges_from_rotation(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted({(min(v,n),max(v,n)) for v,row in enumerate(rotation) for n in row}))


def connected(rotation: Sequence[Sequence[int]], removed: frozenset[int]=frozenset()) -> bool:
    remaining = set(range(len(rotation))) - set(removed)
    if not remaining: return True
    reached = {min(remaining)}; pending = list(reached)
    while pending:
        vertex = pending.pop()
        for neighbor in rotation[vertex]:
            if neighbor in remaining and neighbor not in reached:
                reached.add(neighbor); pending.append(neighbor)
    return reached == remaining


def trace_faces(rotation: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    unused = {(u,v) for u,row in enumerate(rotation) for v in row}; faces=[]
    while unused:
        start=min(unused); dart=start; boundary=[]
        while True:
            if dart not in unused:
                if dart != start: raise ValueError("invalid facial walk")
                break
            unused.remove(dart); left,right=dart; boundary.append(left)
            row=rotation[right]; position=row.index(left)
            dart=(right,row[(position-1)%len(row)])
        faces.append(tuple(boundary))
    return tuple(faces)


def verify_barnette(rotation: Sequence[Sequence[int]], expected_order: int) -> tuple[tuple[int,...],...]:
    if len(rotation) != expected_order or any(len(row) != 3 for row in rotation):
        raise ValueError("wrong order or noncubic graph")
    if not connected(rotation): raise ValueError("disconnected graph")
    colors={0:0}; pending=[0]
    while pending:
        vertex=pending.pop()
        for neighbor in rotation[vertex]:
            if neighbor not in colors: colors[neighbor]=1-colors[vertex]; pending.append(neighbor)
            elif colors[neighbor]==colors[vertex]: raise ValueError("nonbipartite graph")
    for left in range(expected_order):
        if not connected(rotation,frozenset((left,))): raise ValueError("cut vertex")
        for right in range(left+1,expected_order):
            if not connected(rotation,frozenset((left,right))): raise ValueError("two-vertex cut")
    edges=edges_from_rotation(rotation); faces=trace_faces(rotation)
    if expected_order-len(edges)+len(faces)!=2 or sum(map(len,faces))!=2*len(edges):
        raise ValueError("noncellular embedding or failed face arithmetic")
    return faces


def canonical_graph_hash(rotation: Sequence[Sequence[int]]) -> str:
    candidates=[]
    for root in range(len(rotation)):
        for first in rotation[root]:
            for direction in (1,-1):
                labels={root:0,first:1}; parents={root:first,first:root}; vertices=[root,first]; rows=[]; pos=0
                while pos<len(vertices):
                    vertex=vertices[pos]; neighbors=rotation[vertex]; anchor=neighbors.index(parents[vertex])
                    ordered=tuple(neighbors[(anchor+direction*offset)%len(neighbors)] for offset in range(len(neighbors)))
                    for neighbor in ordered:
                        if neighbor not in labels:
                            labels[neighbor]=len(labels); parents[neighbor]=vertex; vertices.append(neighbor)
                    rows.append(tuple(labels[n] for n in ordered)); pos+=1
                candidates.append(tuple(rows))
    return sha256(json.dumps(min(candidates),separators=(",",":")).encode("ascii")).hexdigest()


def graph6(edges: Sequence[tuple[int,int]], order: int) -> str:
    if order > 62: raise ValueError("short graph6 only")
    bits=[]; edge_set=set(edges)
    for right in range(1,order):
        for left in range(right): bits.append(1 if (left,right) in edge_set else 0)
    while len(bits)%6: bits.append(0)
    return chr(order+63)+"".join(chr(63+sum(bits[i+j]<<(5-j) for j in range(6))) for i in range(0,len(bits),6))


def normalize_cycle(cycle: Iterable[int]) -> tuple[int,...]:
    values=tuple(map(int,cycle))
    if len(values)>=2 and values[0]==values[-1]: values=values[:-1]
    variants=[]
    for oriented in (values,tuple(reversed(values))):
        minimum=min(oriented)
        variants.extend(oriented[i:]+oriented[:i] for i,v in enumerate(oriented) if v==minimum)
    return min(variants)


def cycle_edges(cycle: Sequence[int], edge_index: dict[tuple[int,int],int]) -> frozenset[int]:
    chosen=set()
    for left,right in zip(cycle,cycle[1:]+cycle[:1]):
        edge=(min(left,right),max(left,right))
        if edge not in edge_index: raise ValueError("cycle uses nonedge")
        chosen.add(edge_index[edge])
    return frozenset(chosen)


def verify_family(edges: Sequence[tuple[int,int]], cycles_raw: Any, order: int) -> tuple[tuple[tuple[int,...],...],int]:
    if not isinstance(cycles_raw,list): raise ValueError("cycles is not a list")
    cycles=tuple(tuple(map(int,cycle)) for cycle in cycles_raw)
    if len(cycles)!=len(set(cycles)): raise ValueError("duplicate cycles")
    edge_index={edge:i for i,edge in enumerate(edges)}; all_edges=set(range(len(edges))); covered=set()
    for cycle in cycles:
        if len(cycle)!=order or set(cycle)!=set(range(order)) or normalize_cycle(cycle)!=cycle:
            raise ValueError("invalid or nonnormalized Hamiltonian cycle")
        selected=cycle_edges(cycle,edge_index)
        if len(selected)!=order: raise ValueError("cycle has wrong edge count")
        covered.update((a,b) for a in selected for b in all_edges-selected)
    return cycles,len(covered)


def _connected_subset(vertices:set[int], adjacency:Sequence[frozenset[int]])->bool:
    if not vertices:return True
    reached={min(vertices)};pending=list(reached)
    while pending:
        v=pending.pop()
        for n in adjacency[v]&vertices:
            if n not in reached:reached.add(n);pending.append(n)
    return reached==vertices


def enumerate_hamiltonian_cycles(edges:Sequence[tuple[int,int]],order:int)->Iterator[tuple[int,...]]:
    mutable=[set() for _ in range(order)]
    for left,right in edges:mutable[left].add(right);mutable[right].add(left)
    adjacency=tuple(frozenset(row) for row in mutable);all_vertices=set(range(order));path=[0];visited={0}
    def feasible(current:int)->bool:
        remaining=all_vertices-visited;first=path[1]
        if not remaining:return 0 in adjacency[current] and first<current
        if not adjacency[current]&remaining:return False
        if not any(first<v for v in adjacency[0]&remaining):return False
        available=remaining|{0,current}
        return not any(len(adjacency[v]&available)<2 for v in remaining) and _connected_subset(remaining,adjacency)
    def search(current:int)->Iterator[tuple[int,...]]:
        if len(path)==order:
            if 0 in adjacency[current] and path[1]<current:yield tuple(path)
            return
        for candidate in sorted(adjacency[current]-visited,key=lambda v:(len(adjacency[v]-visited),v)):
            visited.add(candidate);path.append(candidate)
            if feasible(candidate):yield from search(candidate)
            path.pop();visited.remove(candidate)
    for first in sorted(adjacency[0]):
        visited.add(first);path.append(first)
        if feasible(first):yield from search(first)
        path.pop();visited.remove(first)


def exhaustive_cover_feasible(edges:Sequence[tuple[int,int]],cycles:Sequence[Sequence[int]],bound:int)->bool:
    if bound<0:return False
    edge_count=len(edges);requirements=tuple((a,b) for a in range(edge_count) for b in range(edge_count) if a!=b);positions={item:i for i,item in enumerate(requirements)}
    edge_index={edge:i for i,edge in enumerate(edges)};all_edges=set(range(edge_count));masks=[];coverers=[[] for _ in requirements]
    for cycle_index,cycle in enumerate(cycles):
        selected=cycle_edges(cycle,edge_index);mask=0
        for required in selected:
            for forbidden in all_edges-selected:
                position=positions[(required,forbidden)];mask|=1<<position;coverers[position].append(cycle_index)
        masks.append(mask)
    if any(not row for row in coverers):return False
    full=(1<<len(requirements))-1;memo={};support_masks=tuple(sum(1<<index for index in row) for row in coverers);packing_order=tuple(sorted(range(len(requirements)),key=lambda index:(support_masks[index].bit_count(),support_masks[index],index)))
    def search(uncovered:int,slots:int)->bool:
        if not uncovered:return True
        if slots==0:return False
        key=(uncovered,slots)
        if key in memo:return memo[key]
        used_support=0;packed=0
        for position in packing_order:
            if uncovered&(1<<position) and not(support_masks[position]&used_support):
                packed+=1
                if packed>slots:memo[key]=False;return False
                used_support|=support_masks[position]
        maximum=max((mask&uncovered).bit_count() for mask in masks)
        if maximum==0 or (uncovered.bit_count()+maximum-1)//maximum>slots:memo[key]=False;return False
        remaining=uncovered;best=None
        while remaining:
            bit=remaining&-remaining;position=bit.bit_length()-1
            candidates=tuple(sorted(coverers[position],key=lambda index:(-(masks[index]&uncovered).bit_count(),index)))
            if best is None or len(candidates)<len(best):best=candidates
            remaining^=bit
        for index in best:
            reduced=uncovered&~masks[index]
            if reduced!=uncovered and search(reduced,slots-1):memo[key]=True;return True
        memo[key]=False;return False
    return search(full,bound)


def verify_graph_record(record:dict[str,Any],index:int,order:int)->tuple[str,tuple[tuple[int,int],...]]:
    if record.get("schema")!=GRAPH_SCHEMA or record.get("generation_index")!=index or record.get("plantri_rank")!=index+1:
        raise ValueError("graph schema/index mismatch")
    data=base64.b64decode(record["planar_code_base64"],validate=True)
    if sha256(data).hexdigest()!=record.get("planar_code_sha256"):raise ValueError("planar_code digest mismatch")
    rotation=parse_planar_code(data);faces=verify_barnette(rotation,order);edges=edges_from_rotation(rotation)
    if [list(row) for row in rotation]!=record.get("rotation_system"):raise ValueError("rotation mismatch")
    if [list(face) for face in faces]!=record.get("faces"):raise ValueError("faces mismatch")
    if sorted(map(len,faces))!=record.get("face_size_multiset"):raise ValueError("face multiset mismatch")
    if [list(edge) for edge in edges]!=record.get("edges") or graph6(edges,order)!=record.get("graph6"):raise ValueError("edge list or graph6 mismatch")
    graph_hash=canonical_graph_hash(rotation)
    if graph_hash!=record.get("canonical_graph_hash"):raise ValueError("canonical hash mismatch")
    return graph_hash,edges


def verify_exact(record:dict[str,Any],edges:Sequence[tuple[int,int]],order:int)->int:
    if record.get("schema")!=EXACT_SCHEMA:raise ValueError("exact schema mismatch")
    exact=record.get("exact_hsep");universe_raw=record.get("complete_hamiltonian_cycle_universe")
    if not isinstance(exact,int) or exact<=0 or not isinstance(universe_raw,list):raise ValueError("invalid exact fields")
    universe,_=verify_family(edges,universe_raw,order)
    if tuple(sorted(universe))!=universe:raise ValueError("unsorted cycle universe")
    independently=tuple(sorted(enumerate_hamiltonian_cycles(edges,order)))
    if independently!=universe:raise ValueError("incomplete Hamiltonian universe")
    primal,covered=verify_family(edges,record.get("primal_cycles"),order)
    requirements=len(edges)*(len(edges)-1)
    if len(primal)!=exact or covered!=requirements:raise ValueError("invalid primal certificate")
    packing=tuple(tuple(map(int,item)) for item in record.get("packing_requirements",[]));method=record.get("lower_bound_method")
    if len(set(packing))!=len(packing) or any(not(0<=a<len(edges) and 0<=b<len(edges) and a!=b) for a,b in packing):raise ValueError("invalid packing requirements")
    if method=="packing":
        if len(packing)!=exact:raise ValueError("invalid packing size")
        edge_index={edge:i for i,edge in enumerate(edges)};all_edges=set(range(len(edges)))
        for cycle in universe:
            selected=cycle_edges(cycle,edge_index)
            if sum(a in selected and b in all_edges-selected for a,b in packing)>1:raise ValueError("packing conflict")
    elif method=="standalone_exhaustive_set_cover":
        if exhaustive_cover_feasible(edges,universe,exact-1):raise ValueError("exhaustive lower bound failed")
    else:raise ValueError("exact record lacks an independently verifiable lower-bound method")
    if record.get("complete_hamiltonian_cycle_count")!=len(universe):raise ValueError("cycle count mismatch")
    return exact


def verify_manifest(directory:Path)->int:
    count=0
    for number,line in enumerate((directory/"SHA256SUMS.txt").read_text(encoding="utf-8").splitlines(),start=1):
        if not line:continue
        try:expected,relative=line.split("  ",1)
        except ValueError as error:raise ValueError(f"bad manifest line {number}") from error
        path=directory/Path(relative)
        if not path.is_file() or digest_file(path)!=expected:raise ValueError(f"manifest mismatch: {relative}")
        count+=1
    return count


def verify_order(root:Path,order:int,check_manifest:bool)->dict[str,Any]:
    directory=root/f"order_{order:02d}";summary=json.loads((directory/"order_summary.json").read_text(encoding="utf-8"));metadata=json.loads((directory/"census_metadata.json").read_text(encoding="utf-8"))
    graphs,gd,gb=read_canonical_gzip(directory/"graph_certificates.jsonl.gz")
    expected=REFERENCE_COUNTS[order] if order%2==0 else 0
    if len(graphs)!=expected:raise ValueError(f"order {order} census count mismatch")
    canonical=metadata.get("canonical_uncompressed",{})
    if expected and (canonical.get("graph_certificates",{}).get("sha256")!=gd or canonical.get("graph_certificates",{}).get("bytes")!=gb):raise ValueError("canonical uncompressed graph digest mismatch")
    if not expected:
        covers,cd,cb=read_canonical_gzip(directory/"cover_certificates.jsonl.gz");exacts,ed,eb=read_canonical_gzip(directory/"exact_certificates.jsonl.gz")
        if covers or exacts or summary.get("M_B") is not None:raise ValueError("empty order has nonempty certificate data")
        return {"order":order,"verified":True,"graph_count":0,"M_B":None,"maximizer_hashes":[],"manifest_files_verified":verify_manifest(directory) if check_manifest else None}
    graph_data={};hashes=set()
    for index,record in enumerate(graphs):
        graph_hash,edges=verify_graph_record(record,index,order)
        if graph_hash in hashes:raise ValueError("duplicate canonical hash")
        hashes.add(graph_hash);graph_data[graph_hash]=edges
    del graphs
    covers,cd,cb=read_canonical_gzip(directory/"cover_certificates.jsonl.gz")
    exacts,ed,eb=read_canonical_gzip(directory/"exact_certificates.jsonl.gz")
    if len(covers)!=expected:raise ValueError(f"order {order} cover count mismatch")
    if any(canonical.get(name,{}).get("sha256")!=digest or canonical.get(name,{}).get("bytes")!=size for name,digest,size in (("cover_certificates",cd,cb),("exact_certificates",ed,eb))):raise ValueError("canonical uncompressed digest mismatch")
    cover_sizes={};requirements=(3*order//2)*(3*order//2-1)
    for index,record in enumerate(covers):
        if record.get("schema")!=COVER_SCHEMA or record.get("generation_index")!=index:raise ValueError("cover schema/index mismatch")
        graph_hash=record.get("canonical_graph_hash");edges=graph_data.get(graph_hash)
        if edges is None:raise ValueError("cover graph identity mismatch")
        cycles,covered=verify_family(edges,record.get("cycles"),order)
        if len(cycles)!=record.get("cover_size") or covered!=requirements:raise ValueError("incomplete separating cover")
        cover_sizes[graph_hash]=len(cycles)
    exact_values={};cycle_counts={}
    for record in exacts:
        graph_hash=record.get("canonical_graph_hash");edges=graph_data.get(graph_hash)
        if edges is None:raise ValueError("exact graph identity mismatch")
        exact_values[graph_hash]=verify_exact(record,edges,order);cycle_counts[graph_hash]=record["complete_hamiltonian_cycle_count"]
    maximum=max(exact_values.values())
    maximizers=sorted(graph_hash for graph_hash,value in exact_values.items() if value==maximum)
    unresolved=[graph_hash for graph_hash,size in cover_sizes.items() if graph_hash not in maximizers and size>=maximum]
    if unresolved:raise ValueError(f"competitors not bounded below maximum: {len(unresolved)}")
    if summary.get("M_B")!=maximum or sorted(summary.get("maximizer_hashes",[]))!=maximizers:raise ValueError("order summary extremal statement mismatch")
    if order<=24 and len(exacts)!=expected:raise ValueError("small-order census is not exact for every graph")
    if order==36 and (maximum!=49 or maximizers!=[BARNIE_HASH] or cycle_counts[BARNIE_HASH]!=68):raise ValueError("order-36 regression failed")
    return {"order":order,"verified":True,"graph_count":expected,"M_B":maximum,"number_of_maximizers":len(maximizers),"maximizer_hashes":maximizers,"ordered_edge_pairs_per_graph":requirements,"manifest_files_verified":verify_manifest(directory) if check_manifest else None}


def verify_all(root:Path,check_manifest:bool,selected_order:int|None=None)->dict[str,Any]:
    started=perf_counter();orders=(selected_order,) if selected_order is not None else ORDERS;results=[]
    for order in orders:results.append(verify_order(root,order,check_manifest))
    if selected_order is None:
        payload=json.loads((root/"barnie_sequence.json").read_text(encoding="utf-8"))
        if [item["order"] for item in payload.get("orders",[])]!=list(ORDERS):raise ValueError("global sequence order list mismatch")
    return {"schema":"barnie-sequence-independent-verification-v1","verified":True,"orders":results,"runtime_seconds":perf_counter()-started,"global_manifest_files_verified":verify_manifest(root) if check_manifest and selected_order is None else None}


def main(argv:Sequence[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("root",type=Path);parser.add_argument("--check-manifest",action="store_true");parser.add_argument("--manifest-only",action="store_true");parser.add_argument("--order",type=int);parser.add_argument("--report",type=Path);args=parser.parse_args(argv)
    try:
        if args.manifest_only:
            count=verify_manifest(args.root);result={"schema":"barnie-sequence-manifest-verification-v1","verified":True,"manifest_files_verified":count}
        else:result=verify_all(args.root,args.check_manifest,args.order)
    except Exception as error:
        print(canonical_json({"verified":False,"error":str(error)}));return 1
    output=canonical_json(result)
    if args.report:
        temporary=args.report.with_name(args.report.name+".tmp");temporary.write_text(output+"\n",encoding="ascii",newline="\n");temporary.replace(args.report)
    print(output);return 0


if __name__=="__main__":sys.exit(main())
