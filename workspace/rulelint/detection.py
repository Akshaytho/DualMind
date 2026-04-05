"""Graph-based conflict detection — 5 algorithms, 1 entry point."""

from __future__ import annotations

import networkx as nx

from .models import Conflict, ConflictType, Rule


def detect_conflicts(rules: list[Rule]) -> list[Conflict]:
    """Run all 5 detection algorithms. Single entry point per Arjun's ask."""
    conflicts: list[Conflict] = []
    rule_map = {r.rule_id: r for r in rules}
    graph = _build_dependency_graph(rules)

    conflicts.extend(_detect_contradictions(rules, rule_map))
    conflicts.extend(_detect_circular_dependencies(graph, rule_map))
    conflicts.extend(_detect_dead_rules(rules, rule_map))
    conflicts.extend(_detect_jurisdictional_overlaps(rules))
    conflicts.extend(_detect_supersession_chains(rules, rule_map))

    return conflicts


def _build_dependency_graph(rules: list[Rule]) -> nx.DiGraph:
    """Build a directed graph: edge A→B means A depends on B."""
    g = nx.DiGraph()
    for r in rules:
        g.add_node(r.rule_id)
        for dep in r.depends_on:
            g.add_edge(r.rule_id, dep)
    return g


def _detect_contradictions(rules: list[Rule], rule_map: dict[str, Rule]) -> list[Conflict]:
    """Two active rules from different authorities with opposing types on same domain."""
    conflicts = []
    active = [r for r in rules if r.status == "active"]
    opposites = {
        ("requirement", "prohibition"),
        ("prohibition", "requirement"),
        ("permission", "prohibition"),
        ("prohibition", "permission"),
    }

    seen = set()
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if a.authority != b.authority and (a.rule_type, b.rule_type) in opposites:
                pair = tuple(sorted([a.rule_id, b.rule_id]))
                if pair not in seen:
                    seen.add(pair)
                    conflicts.append(
                        Conflict(
                            conflict_type=ConflictType.CONTRADICTION,
                            rule_ids=list(pair),
                            description=f"{a.rule_id} ({a.authority}/{a.rule_type}) contradicts {b.rule_id} ({b.authority}/{b.rule_type})",
                            severity="high",
                        )
                    )
    return conflicts


def _detect_circular_dependencies(graph: nx.DiGraph, rule_map: dict[str, Rule]) -> list[Conflict]:
    """Find cycles in the dependency graph."""
    conflicts = []
    try:
        cycles = list(nx.simple_cycles(graph))
    except nx.NetworkXError:
        return conflicts

    for cycle in cycles:
        conflicts.append(
            Conflict(
                conflict_type=ConflictType.CIRCULAR_DEPENDENCY,
                rule_ids=cycle,
                description=f"Circular dependency: {' → '.join(cycle)} → {cycle[0]}",
                severity="high",
            )
        )
    return conflicts


def _detect_dead_rules(rules: list[Rule], rule_map: dict[str, Rule]) -> list[Conflict]:
    """Active rules that depend on repealed/superseded rules."""
    conflicts = []
    for r in rules:
        if r.status != "active":
            continue
        for dep_id in r.depends_on:
            dep = rule_map.get(dep_id)
            if dep and dep.status in ("repealed", "superseded"):
                conflicts.append(
                    Conflict(
                        conflict_type=ConflictType.DEAD_RULE,
                        rule_ids=[r.rule_id, dep_id],
                        description=f"{r.rule_id} (active) depends on {dep_id} (status: {dep.status})",
                        severity="medium",
                    )
                )
    return conflicts


def _detect_jurisdictional_overlaps(rules: list[Rule]) -> list[Conflict]:
    """Same-type rules from different authorities covering the same domain."""
    conflicts = []
    active = [r for r in rules if r.status == "active"]
    seen = set()

    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            if (
                a.authority != b.authority
                and a.rule_type == b.rule_type
                and a.domain == b.domain
                and (a.rule_type, b.rule_type) not in {("requirement", "prohibition"), ("prohibition", "requirement"), ("permission", "prohibition"), ("prohibition", "permission")}
            ):
                pair = tuple(sorted([a.rule_id, b.rule_id]))
                if pair not in seen:
                    seen.add(pair)
                    conflicts.append(
                        Conflict(
                            conflict_type=ConflictType.JURISDICTIONAL_OVERLAP,
                            rule_ids=list(pair),
                            description=f"{a.rule_id} ({a.authority}) and {b.rule_id} ({b.authority}) both {a.rule_type} on {a.domain}",
                            severity="low",
                        )
                    )
    return conflicts


def _detect_supersession_chains(rules: list[Rule], rule_map: dict[str, Rule]) -> list[Conflict]:
    """Detect chains where A supersedes B supersedes C — flag if chain > 2."""
    conflicts = []
    supersedes_map = {r.rule_id: r.supersedes for r in rules if r.supersedes}

    for start_id in supersedes_map:
        chain = [start_id]
        current = supersedes_map.get(start_id)
        visited = {start_id}

        while current and current not in visited:
            chain.append(current)
            visited.add(current)
            current = supersedes_map.get(current)

        if len(chain) > 2:
            conflicts.append(
                Conflict(
                    conflict_type=ConflictType.SUPERSESSION_CHAIN,
                    rule_ids=chain,
                    description=f"Long supersession chain: {' → '.join(chain)}",
                    severity="low",
                )
            )
    return conflicts
