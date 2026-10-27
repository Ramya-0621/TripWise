"""
search_algorithms.py  -  GENERIC SEARCH TOOLS
=============================================
Three small, reusable algorithms. They know nothing about travel; the
recommender plugs in the travel-specific rules.

1. filter_destinations()  CONSTRAINT-BASED PRUNING
   Applies a list of named hard constraints. A destination survives only if it
   passes ALL of them. Rejected ones are recorded with the reason, so we can
   explain failures later.

2. bfs_search()           BREADTH-FIRST SEARCH
   Explores a state space level by level using a FIFO queue:
       level 0: start
       level 1: destination chosen
       level 2: transport chosen
       level 3: accommodation chosen
       level 4+: activities added one by one  -> 'complete' states are goals
   Every child state is checked by a `prune` function BEFORE it enters the queue.
   A pruned state is never expanded, so whole branches of the search tree
   (e.g. every itinerary that begins with an unaffordable flight) are skipped.

3. top_k()                PRIORITY-BASED RANKING
   Uses heapq.nlargest (a heap) to pull the best k items without fully sorting.
"""
import heapq
from collections import deque, Counter


def filter_destinations(destinations, constraints):
    """
    constraints: list of (name, predicate). predicate(dest) -> True keeps it.
    Returns (kept, rejected) where rejected maps constraint name -> [dest ids].
    A destination is attributed to the FIRST constraint it fails.
    """
    kept, rejected = [], {}
    for dest in destinations:
        for name, predicate in constraints:
            if not predicate(dest):
                rejected.setdefault(name, []).append(dest["id"])
                break
        else:
            kept.append(dest)
    return kept, rejected


def bfs_search(start, expand, is_goal, prune=None, max_nodes=200_000):
    """
    Breadth-first search.
      start    - initial state
      expand   - function(state) -> list of child states
      is_goal  - function(state) -> True when the state is a finished itinerary
      prune    - optional function(child) -> True to discard the child immediately
    Returns (goal_states, stats). `stats` counts nodes for explanation/debugging.
    """
    queue = deque([start])              # FIFO queue = breadth-first order
    goals = []
    stats = {"expanded": 0, "generated": 0, "pruned": 0, "pruned_by_stage": Counter(), "truncated": False}

    while queue:
        state = queue.popleft()
        if is_goal(state):
            goals.append(state)
            continue                    # a finished itinerary has no children
        stats["expanded"] += 1
        if stats["expanded"] > max_nodes:   # safety net for huge knowledge bases
            stats["truncated"] = True
            break
        for child in expand(state):
            stats["generated"] += 1
            if prune is not None and prune(child):
                stats["pruned"] += 1
                stats["pruned_by_stage"][child.stage] += 1
                continue                # early pruning: never explore this branch
            queue.append(child)

    stats["pruned_by_stage"] = dict(stats["pruned_by_stage"])
    return goals, stats


def top_k(items, k, key):
    """Return the k highest-scoring items (a heap is used under the hood)."""
    return heapq.nlargest(k, items, key=key)
