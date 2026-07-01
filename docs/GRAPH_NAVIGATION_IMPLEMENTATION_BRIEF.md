# Aryx Graph Navigation Improvement Brief

**Status:** Proposed for implementation  
**Audience:** Business stakeholders, product, design, and engineering  
**Prepared for:** Graph usability improvement decision  
**Date:** 2026-06-26

## 1. Executive Summary

The current Aryx Graph page is technically functional, but it is not easy to read or navigate when the graph becomes dense. Users land on a full instance-level view that collapses into a narrow vertical structure with large empty canvas areas. As a result, users struggle to understand the graph, find a specific region, or move confidently between connected areas.

The recommended solution is to change the default experience from **full graph first** to **overview first**.

Instead of immediately rendering every entity instance, Aryx should initially show a simplified, Protege-like overview made of major entity groups or hub entities. Users can then expand one region at a time into a local neighborhood view. This reduces cognitive overload, makes the graph understandable at first glance, and gives users a reliable path from overview to detail.

This work should be implemented as a usability improvement, not as a graph engine rewrite.

## 2. Problem Statement

### What users experience today

- The graph opens in a fully expanded instance-level canvas.
- Nodes are visually compressed into a tall, thin stack.
- Large empty areas of canvas make navigation feel disconnected.
- Zoom controls are present, but zooming alone does not help users understand where they are.
- A minimap is visible, but it is not reliable enough to act as the primary navigation aid.
- Existing search and focus interactions are helpful but not strong enough to create a fast "take me to the right area" workflow.

### Why this matters

- Business users may conclude the graph is too complicated, even when the underlying data is correct.
- Technical users spend time fighting the visualization instead of exploring relationships.
- First impressions of the Graph page are weaker than the value of the Aryx knowledge graph itself.
- Poor navigation reduces trust, adoption, and demo clarity.

## 3. Key Observation

This is primarily a **navigation and presentation problem**, not a missing-zoom problem.

The current UI already includes useful building blocks:

- Search
- Type filters
- Reset view
- Node focus
- Path finder
- Minimap
- Zoom controls

The main gap is that these capabilities do not combine into a clear, progressive exploration model.

## 4. Recommendation

### Primary decision

Adopt an **Overview-First Graph Experience** as the default Graph page behavior.

### Core interaction model

1. When a user opens the Graph page, show a simplified overview instead of the full instance graph.
2. The overview should display either:
   - major entity types with counts, or
   - major hub entities / clusters, depending on which is clearer for the dataset.
3. When a user clicks an overview node, Aryx should expand only that region into a local neighborhood view.
4. Once inside a local neighborhood, users can:
   - zoom,
   - pan,
   - inspect node details,
   - run path finder,
   - search within context,
   - return to overview.

### Product framing

The Graph page should behave less like a raw graph dump and more like a guided exploration tool.

## 5. Proposed User Experience

### Default landing state

Show a high-level graph overview similar to ontology tools such as Protege:

- one node per major entity type or cluster
- counts visible on nodes, for example `PCage (62)`
- simplified relationship lines between overview nodes
- stable layout with minimal overlap
- no attempt to render every instance immediately

### First drill-down

When the user selects an overview node:

- expand into a local subgraph
- show the selected node or cluster plus 1-hop neighbors by default
- optionally allow 2-hop expansion when requested
- center and fit the selected region automatically

### Ongoing navigation

Within the local subgraph:

- keep existing zoom controls
- retain filters and path finder
- improve search so it not only filters, but also jumps to and centers the selected result
- keep the minimap only if it can be made reliable; otherwise treat it as secondary

### Return path

Users should always have an obvious way to:

- return to overview
- reset the view
- switch to full graph only when needed

## 6. Business Benefits

### For product and customer-facing teams

- Improves first-time comprehension of the graph
- Makes demos easier to explain
- Reduces the perception that the graph is "too technical"
- Increases confidence that Aryx organizes information in a deliberate way
- Supports broader stakeholder adoption across business and operational users

### For delivery and support teams

- Reduces usability complaints related to graph clutter
- Shortens onboarding time for new users
- Makes path-based and entity-based exploration easier to teach

## 7. Technical Direction

### Recommended implementation approach

Implement this in phases, reusing the current Graph page architecture.

### Phase 1: Overview-first landing

Deliver a new default mode for the Graph page:

- `Overview` mode becomes the default
- render type-level or cluster-level nodes first
- show entity counts per overview node
- use a more stable, compact layout than the current fully expanded force layout

### Phase 2: Progressive expansion

Add contextual drill-down behavior:

- click overview node -> open local neighborhood
- auto-fit and center the selected region
- preserve back navigation to overview

### Phase 3: Navigation refinement

Improve quick movement within the graph:

- search should jump to the selected area
- focus action should be more visible
- path results should automatically frame the discovered path
- minimap should either be fixed or de-emphasized if it remains unreliable

## 8. Scope Definition

### In scope

- Default Graph page behavior
- Overview representation
- Progressive drill-down
- Search-to-focus improvement
- Auto-fit / center selected region
- Better use of existing navigation actions

### Out of scope

- Replacing the graph database
- Reworking ingestion or ontology generation
- Rebuilding graph storage or query APIs
- Major backend architecture changes unrelated to visualization

## 9. UX Options Considered

### Option A: Keep full graph as default and improve zoom/minimap

**Assessment:** Not recommended as the primary solution.

Reason:
The graph still opens in a cognitively overwhelming state. Better controls help only after the user is already lost.

### Option B: Overview-first with progressive reveal

**Assessment:** Recommended.

Reason:
This matches how users naturally explore complexity: start broad, then expand only the relevant area.

### Option C: Full graph plus automatic clustering only

**Assessment:** Useful as a supporting technique, but not enough on its own.

Reason:
Clustering may reduce visual noise, but without an explicit overview mode and drill-down pattern, the experience can still feel ambiguous.

## 10. Delivery Plan

### Suggested sequence

1. Define overview model:
   - type-based overview
   - hub-based overview
   - or hybrid
2. Implement Overview mode in the Graph page.
3. Add click-to-expand local neighborhood behavior.
4. Add fit-to-selection and search-to-focus behavior.
5. Validate with a real workspace that currently produces the tall vertical layout.
6. Decide whether to keep, fix, or de-emphasize the minimap.

## 11. Acceptance Criteria

The implementation should be considered successful when:

- A first-time user can identify the main graph areas within a few seconds.
- The Graph page no longer opens in a visually overwhelming full-instance layout by default.
- Clicking a major entity group or hub clearly reveals a focused local graph region.
- Search reliably takes the user to the relevant area.
- Reset and return-to-overview actions are obvious and dependable.
- Users can inspect a specific area without needing to manually navigate the entire graph.

## 12. Risks and Mitigations

### Risk: Overview is too abstract for some users

**Mitigation:** Provide a visible `Overview | Full graph` toggle.

### Risk: Wrong overview grouping model

**Mitigation:** Start with type-based grouping because it is easier to explain and aligns with the ontology mental model.

### Risk: Minimap remains confusing

**Mitigation:** Treat the minimap as optional support, not the primary navigation pattern.

### Risk: Layout still feels unstable after drill-down

**Mitigation:** Apply auto-fit on selection and use a tighter layout configuration for local neighborhoods.

## 13. Recommended Decision

Proceed with an **overview-first graph redesign** using a **type-based default overview** and **progressive drill-down into local neighborhoods**.

This is the most practical path because it:

- solves the actual usability problem,
- aligns with how ontology tools present complexity,
- reuses current Aryx graph capabilities,
- and creates a cleaner experience for both business and technical users.

## 14. Technical Notes for Engineering Handoff

The current Graph page already contains reusable pieces that support this direction:

- Graph page rendering and controls:
  - [src/aryx/ui/graph_panel.py](/Users/gigggsoa22/giggso/aryx/src/aryx/ui/graph_panel.py)
- Canvas node/edge construction and layout config:
  - [src/aryx/ui/graph_canvas.py](/Users/gigggsoa22/giggso/aryx/src/aryx/ui/graph_canvas.py)
- Drill-down and path behavior:
  - [src/aryx/ui/graph_detail.py](/Users/gigggsoa22/giggso/aryx/src/aryx/ui/graph_detail.py)
- Existing ontology diagram reference for simplified graph presentation:
  - [src/aryx/ui/ontology_diagram.py](/Users/gigggsoa22/giggso/aryx/src/aryx/ui/ontology_diagram.py)

### Suggested implementation shape

- Add a graph mode switch:
  - `Overview`
  - `Focused`
  - optional `Full graph`
- Build an overview node set from current graph entities:
  - first candidate: aggregate by `type`
- Add a selection state that expands one overview node into visible instances and nearby relationships
- Rework default layout sizing for overview and focused modes separately
- Make search produce focus behavior, not just filtering behavior

## 15. Final Summary

The right next step is not to add more controls to the current full graph view.

The right next step is to change the default graph experience so users start with a clear overview, then progressively open the area they care about. That approach is easier to understand, easier to demo, and more aligned with the business value Aryx is trying to communicate.
