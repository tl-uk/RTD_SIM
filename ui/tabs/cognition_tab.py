"""
ui/tabs/cognition_tab.py

Agent Cognition Diagnostics Tab — Phase 2 + 3 observability.

Shows three panels:
  1. Influence Network     — who peers with whom, edge weight = influence strength
  2. Belief Drift          — how belief.strength evolves over time per agent
  3. Markov Habit Heatmap  — transition matrices and habit lock-in per persona

All panels derive data purely from results.agents and results.network,
which are already in session state after a simulation run.
"""

import streamlit as st
import sys
from pathlib import Path

parent_dir = Path(__file__).resolve().parent.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


# ── helpers ──────────────────────────────────────────────────────────────

def _story_agents(results):
    """Return only agents that have user_story + mode_chain (story-driven)."""
    if not results or not results.agents:
        return []
    return [
        a for a in results.agents
        if hasattr(a, 'user_story') and hasattr(a, 'mode_chain')
    ]


def _belief_snapshot(agent):
    """Return list of (text_short, strength) for the agent's beliefs."""
    beliefs = getattr(getattr(agent, 'user_story', None), 'beliefs', [])
    return [
        (getattr(b, 'text', '')[:35], round(float(getattr(b, 'strength', 0.5)), 3))
        for b in beliefs
    ]


def _markov_summary(agent):
    """Return mode_chain.summary() or None."""
    chain = getattr(agent, 'mode_chain', None)
    if chain is None:
        return None
    try:
        return chain.summary()
    except Exception:
        return None


def _peer_edges(results, max_edges=120):
    """
    Extract edges from SocialNetwork for the focal (story) agents.
 
    Returns ALL edges from focal agents regardless of where the target is.
    Ghost nodes (non-story neighbours) are added by the renderer so edges
    actually appear. max_edges raised to 120 because ghost nodes make the
    graph denser and more informative.
    """
    network = getattr(results, 'network', None)
    if network is None:
        return []
 
    edges = []
    agents = _story_agents(results)
    seen = set()
 
    # Pick focal agents: prefer those with the most connections to other
    # story agents (most informative for the viewer). Fall back to [:40].
    story_ids = {a.state.agent_id for a in agents}
    scored = []
    for agent in agents:
        aid = agent.state.agent_id
        try:
            neighbors = network.get_neighbors(aid) or []
        except Exception:
            neighbors = []
        within_story = sum(1 for nb in neighbors if nb in story_ids)
        scored.append((agent, within_story))
 
    # Sort by within-story connections descending, take top 40
    scored.sort(key=lambda x: x[1], reverse=True)
    focal_agents = [a for a, _ in scored[:40]]
 
    for agent in focal_agents:
        aid = agent.state.agent_id
        try:
            neighbors = network.get_neighbors(aid)
        except Exception:
            break
 
        for nb_id in (neighbors or []):
            key = tuple(sorted([aid, nb_id]))
            if key in seen:
                continue
            seen.add(key)
            # No endpoint filter here — ghost nodes added by renderer
            edges.append({'source': aid, 'target': nb_id, 'weight': 1.0})
            if len(edges) >= max_edges:
                return edges
 
    return edges


# ── main render ──────────────────────────────────────────────────────────

def render_cognition_tab(results, anim=None, current_data=None):
    """Render the Agent Cognition Diagnostics tab."""

    st.markdown("## 🧠 Agent Cognition Diagnostics")
    st.caption(
        "Live view of how Bayesian belief updating (Phase 2) and "
        "Markov habit formation (Phase 3) are shaping agent decisions."
    )

    agents = _story_agents(results)

    if not agents:
        st.info(
            "No story-driven agents found in this run. "
            "Run a simulation with user story + job story combinations to see cognition data."
        )
        return

    # ── top-level summary metrics ────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    # Belief drift: how many beliefs have shifted by >5%
    drifted = 0
    for a in agents:
        for _, strength in _belief_snapshot(a):
            if abs(strength - 0.5) > 0.05:
                drifted += 1

    # Habit lock-in: agents where any mode P(stay) > 0.7
    locked = sum(
        1 for a in agents
        if any(
            v > 0.70
            for v in (_markov_summary(a) or {}).get('habits', {}).values()
        )
    )

    # Peer influence: average eco desire
    eco_vals = [a.desires.get('eco', 0.5) for a in agents if hasattr(a, 'desires')]
    avg_eco = sum(eco_vals) / len(eco_vals) if eco_vals else 0.5

    # CPG activations: agents whose context has been enriched by belief updater
    enriched = sum(
        1 for a in agents
        if hasattr(a, 'agent_context')
        and 'charger_occupancy_nearby' in a.agent_context
    )

    col1.metric("Story Agents", len(agents))
    col2.metric("Beliefs Shifted", drifted, help="Beliefs where strength deviated >5% from prior")
    col3.metric("Habit-locked Agents", locked, help="Agents with P(stay in mode) > 70%")
    col4.metric("Eco Desire (avg)", f"{avg_eco:.2f}", help="Mean eco desire across all agents; peer influence nudges this")

    st.markdown("---")

    # ── three diagnostic panels ──────────────────────────────────────────
    tab_influence, tab_beliefs, tab_markov = st.tabs([
        "🌐 Influence Network",
        "📊 Belief Drift",
        "🔀 Markov Habits",
    ])

    # ── Panel 1: Influence Network ────────────────────────────────────────
    with tab_influence:
        _render_influence_network(results, agents)

    # ── Panel 2: Belief Drift ─────────────────────────────────────────────
    with tab_beliefs:
        _render_belief_drift(agents)

    # ── Panel 3: Markov Habits ────────────────────────────────────────────
    with tab_markov:
        _render_markov_habits(agents)


# ── Panel implementations ─────────────────────────────────────────────────

def _render_influence_network(results, agents):
    st.markdown("### 🌐 Social Influence Network")
    st.caption(
        "Nodes = agents. Edges = peer connections in the homophily-based social network. "
        "Node colour encodes current eco desire (green = high, grey = low). "
        "Hover a node to see belief strength and current mode."
    )

    try:
        import json
        edges = _peer_edges(results)

        # Build agent lookup keyed by agent_id for O(1) access below.
        agent_by_id = {a.state.agent_id: a for a in agents}

        # Derive focal agent IDs directly from edge sources.
        # _peer_edges() selects its own focal_agents (top-40 by within-story
        # connections) — the set is NOT the same as agents[:40] (list-index
        # order).  Using agents[:40] for node_meta means the source guard in
        # the ghost-node and edge passes silently drops every edge:
        #     if e['source'] not in node_meta: continue   ← always true
        # Fix: mirror _peer_edges' focal set by reading source IDs straight
        # from the returned edges. dict.fromkeys preserves insertion order and
        # deduplicates without a separate seen-set.
        focal_source_ids = dict.fromkeys(e['source'] for e in edges)

        # Build node list with metadata from the actual focal agents.
        node_meta = {}
        for aid in focal_source_ids:
            a = agent_by_id.get(aid)
            if a is None:
                continue
            eco   = a.desires.get('eco', 0.5) if hasattr(a, 'desires') else 0.5
            mode  = getattr(a.state, 'mode', 'walk')
            label = aid.rsplit('_', 1)[0]   # strip trailing random seed
            ctx   = getattr(a, 'agent_context', {})
            occ   = ctx.get('charger_occupancy_nearby', None)
            peer_ev = ctx.get('peer_ev_rate', None)
            beliefs = _belief_snapshot(a)
            belief_str = '; '.join(f"{t}: {s}" for t, s in beliefs[:3])

            # Build tooltip as a <table> — avoids <br/> serialisation
            # issues in pyvis/vis.js across different versions.
            rows = [
                f"<tr><td colspan='2'><b>{label}</b></td></tr>",
                f"<tr><td>Mode</td><td>{mode}</td></tr>",
                f"<tr><td>Eco desire</td><td>{eco:.2f}</td></tr>",
            ]
            if occ is not None:
                rows.append(f"<tr><td>Charger occ.</td><td>{occ:.0%}</td></tr>")
            if peer_ev is not None:
                rows.append(f"<tr><td>Peer EV rate</td><td>{peer_ev:.0%}</td></tr>")
            if belief_str:
                rows.append(f"<tr><td colspan='2' style='font-size:10px'>{belief_str}</td></tr>")

            tooltip = (
                "<table style='border-collapse:collapse;font-size:12px;"
                "font-family:sans-serif;background:#1e2130;color:#e0e0e0;"
                "padding:4px'>"
                + "".join(rows)
                + "</table>"
            )
            node_meta[aid] = {'eco': eco, 'mode': mode, 'tooltip': tooltip}

        if not edges:
            st.info(
                "No peer edges found. The social network may not have been built "
                "for this run, or `network.get_neighbors()` is not implemented. "
                "Check that `config.enable_social = True` and the network was set up."
            )
            return

        # Render with pyvis if available, else Streamlit native graph
        try:
            from pyvis.network import Network as PyvisNetwork
            import tempfile, os

            net = PyvisNetwork(
                height="480px", width="100%",
                bgcolor="transparent", font_color="#444"
            )
            net.set_options("""
            {
              "physics": {
                "stabilization": {"iterations": 150},
                "barnesHut": {"gravitationalConstant": -3000, "springLength": 120}
              },
              "nodes": {"shape": "dot", "scaling": {"min": 10, "max": 24}},
              "edges": {
                "color": {"opacity": 0.5},
                "smooth": {"type": "continuous"}
              },
              "interaction": {"hover": true, "tooltipDelay": 100}
            }
            """)

            for aid, meta in node_meta.items():
                eco   = meta['eco']
                r     = int(40  + (1 - eco) * 120)   # green tones
                g     = int(120 + eco * 100)
                b     = int(60  + (1 - eco) * 60)
                color = f"#{r:02x}{g:02x}{b:02x}"
                net.add_node(
                    aid,
                    label=aid.split('generated_')[0].rstrip('_')[-18:],
                    title=meta['tooltip'],
                    color=color,
                    size=12 + eco * 10,
                )

            # Add ghost nodes for targets outside the focal set.
            # Ghost = small grey unlabelled dot. Shows the real connection
            # without cluttering with agent detail. Avoids "non existent node".
            ghost_ids: set = set()
            for e in edges:
                if e['source'] not in node_meta:
                    continue          # source not focal — skip
                if e['target'] in node_meta or e['target'] in ghost_ids:
                    continue          # already added
                # Add ghost node for this neighbour.
                # title must be a plain string — pyvis escapes bare <span>
                # tags as raw text. Full agent id is the most useful hover.
                net.add_node(
                    e['target'],
                    label='',
                    title=e['target'],
                    color='#9e9e9e',
                    size=5,
                )
                ghost_ids.add(e['target'])
 
            # Now add edges — source is in focal set, target is focal or ghost
            for e in edges:
                if e['source'] not in node_meta:
                    continue
                if e['target'] not in node_meta and e['target'] not in ghost_ids:
                    continue
                # Thicker line between two focal agents; thinner to ghost
                width = 1.5 if e['target'] in node_meta else 0.7
                net.add_edge(e['source'], e['target'], width=width)


            with tempfile.NamedTemporaryFile(
                delete=False, suffix='.html', mode='w'
            ) as f:
                net.save_graph(f.name)
                html_path = f.name
 
            with open(html_path) as f:
                html_content = f.read()
            os.unlink(html_path)
 
            # Inject CSS to centre the graph and remove iframe margins.
            # Pyvis names its canvas div #mynetwork by default.
            # The <style> injection goes right after the opening <head> tag.
            centering_css = """
                <style>
                html, body {
                    margin: 0 !important;
                    padding: 0 !important;
                    width: 100%;
                    height: 100%;
                    overflow: hidden;
                    background: transparent;
                }
                #mynetwork {
                    width: 100% !important;
                    height: 500px !important;
                    border: none !important;
                    background: transparent !important;
                }
                </style>
                """
            html_content = html_content.replace("<head>", "<head>" + centering_css, 1)
                
            st.components.v1.html(html_content, height=520, scrolling=False)

        except ImportError:
            # Fallback: simple table showing connections
            st.warning(
                "pyvis not installed — showing edge table instead. "
                "Install with: `pip install pyvis`"
            )
            import pandas as pd
            df = pd.DataFrame(edges)
            # Add eco values
            df['source_eco'] = df['source'].map(
                lambda x: f"{node_meta.get(x, {}).get('eco', 0):.2f}"
            )
            df['target_eco'] = df['target'].map(
                lambda x: f"{node_meta.get(x, {}).get('eco', 0):.2f}"
            )
            st.dataframe(df, use_container_width=True)

    except Exception as e:
        st.error(f"Influence network render failed: {e}")

    # Explain what the updater is doing
    with st.expander("How peer influence flows into BDI"):
        st.markdown("""
        **Before Phase 2** — `apply_social_influence()` in the simulation loop directly 
        overwrote `agent.state.mode`, bypassing the BDI planner entirely.

        **After Phase 2** — `BayesianBeliefUpdater._reweight_desires_from_peers()` computes 
        the EV adoption rate among the agent's immediate neighbours and nudges 
        `agent.desires['eco']` by up to ±0.03 per update cycle (every 5 steps).

        The BDI planner then scores modes using the updated desire weights — social influence 
        now flows *through* the belief-desire-intention cycle rather than short-circuiting it.

        **What the colour encodes**: green nodes have high `eco` desire (prefer EV/bike/bus), 
        grey nodes have low `eco` desire (prefer car). As peer influence accumulates over 
        200 steps, you should see clusters of similar-coloured nodes forming — this is 
        emergent homophily-driven opinion convergence.
        """)


def _render_belief_drift(agents):
    st.markdown("### 📊 Belief Strength — Current Snapshot")
    st.caption(
        "Each row is one belief across agents. Bar length = current strength [0,1]. "
        "Beliefs drift from their story-defined priors based on personal satisfaction "
        "and peer observations (Phase 2 Bayesian update)."
    )

    import pandas as pd

    # Gather all belief texts across all agents
    belief_map = {}   # belief_text → list of (agent_id, strength, persona)
    for a in agents:
        persona = getattr(a, 'user_story_id', '?')
        for text, strength in _belief_snapshot(a):
            if not text:
                continue
            if text not in belief_map:
                belief_map[text] = []
            belief_map[text].append({
                'agent': a.state.agent_id.rsplit('_', 2)[0][-22:],
                'persona': persona,
                'strength': strength,
            })

    if not belief_map:
        st.info("No belief data found. Agents may not have run long enough for beliefs to be extracted.")
        return

    # Show top 12 most-varied beliefs (highest std dev of strength)
    import statistics
    beliefs_sorted = sorted(
        belief_map.items(),
        key=lambda kv: (
            statistics.stdev([r['strength'] for r in kv[1]])
            if len(kv[1]) > 1 else 0
        ),
        reverse=True
    )[:12]

    for belief_text, records in beliefs_sorted:
        strengths = [r['strength'] for r in records]
        mean_s   = sum(strengths) / len(strengths)
        std_s    = statistics.stdev(strengths) if len(strengths) > 1 else 0
        min_s    = min(strengths)
        max_s    = max(strengths)

        col_label, col_bar, col_stats = st.columns([3, 5, 2])
        with col_label:
            st.markdown(f"**{belief_text}**")
            st.caption(f"{len(records)} agents")
        with col_bar:
            # Draw a horizontal range bar using st.progress approximation
            # Use a mini dataframe chart for the distribution
            df_b = pd.DataFrame({'strength': strengths})
            st.bar_chart(df_b['strength'].value_counts(bins=8).sort_index(), height=60)
        with col_stats:
            st.markdown(
                f"μ = **{mean_s:.2f}**  \nσ = {std_s:.2f}  \n"
                f"[{min_s:.2f} – {max_s:.2f}]"
            )

    st.markdown("---")

    # Per-agent belief table for a selected agent
    st.markdown("#### Inspect individual agent beliefs")
    agent_ids = [a.state.agent_id for a in agents]
    selected_id = st.selectbox("Select agent", agent_ids, key="cognition_agent_select")
    selected = next((a for a in agents if a.state.agent_id == selected_id), None)

    if selected:
        persona_id = getattr(selected, 'user_story_id', '?')
        job_id     = getattr(selected, 'job_story_id', '?')
        mode       = getattr(selected.state, 'mode', '?')
        eco        = selected.desires.get('eco', 0.5) if hasattr(selected, 'desires') else '?'
        ctx        = getattr(selected, 'agent_context', {})

        st.markdown(
            f"**{selected_id}**  \n"
            f"Persona: `{persona_id}` · Job: `{job_id}` · Mode: `{mode}`  \n"
            f"Eco desire: `{eco:.3f}` · "
            f"Charger occ nearby: `{ctx.get('charger_occupancy_nearby', 'n/a')}` · "
            f"Peer EV rate: `{ctx.get('peer_ev_rate', 'n/a')}`"
        )

        beliefs = _belief_snapshot(selected)
        if beliefs:
            rows = []
            for text, strength in beliefs:
                delta = strength - 0.5
                arrow = "↑" if delta > 0.05 else ("↓" if delta < -0.05 else "→")
                rows.append({
                    'Belief': text,
                    'Strength': strength,
                    'vs prior 0.5': f"{arrow} {delta:+.2f}",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("No beliefs recorded for this agent.")

    with st.expander("How belief updating works (Bayesian)"):
        st.markdown("""
**Update formula** (called every 5 simulation steps):

```
posterior = 0.50 × prior
          + 0.35 × avg_satisfaction_for_relevant_mode (last 8 steps)
          + 0.15 × peer_EV_adoption_rate (for EV-related beliefs)
```

**Example**: An agent with belief *"EVs are eco-friendly"* (prior = 0.8) 
experiences three charging delays (satisfaction ≈ 0.3). After 15 steps:

```
posterior ≈ 0.50 × 0.8 + 0.35 × 0.3 + 0.15 × 0.5 = 0.580
```

The belief weakens — the agent starts to factor EV reliability into future decisions.

**What to look for**: High σ (standard deviation) across agents for the same belief 
means the simulation is producing realistic heterogeneous outcomes. If all strengths 
are ≈ 0.5, agents aren't experiencing enough variation in satisfaction scores — try 
reducing charger count to create more contention.
        """)


def _render_markov_habits(agents):
    st.markdown("### 🔀 Markov Habit Formation")
    st.caption(
        "Each agent's `PersonalityMarkovChain` learns which modes it uses repeatedly. "
        "The diagonal of the transition matrix = P(stay in current mode). "
        "High diagonal = strong habit lock-in."
    )

    import pandas as pd

    # ── 1. Population-level habit summary ────────────────────────────────
    st.markdown("#### Habit strength by persona type")

    persona_habits: dict = {}   # persona_id → {mode: [strength, ...]}
    for a in agents:
        persona = getattr(a, 'user_story_id', 'unknown')
        summary = _markov_summary(a)
        if not summary:
            continue
        if persona not in persona_habits:
            persona_habits[persona] = {}
        for mode, strength in summary.get('habits', {}).items():
            persona_habits[persona].setdefault(mode, []).append(strength)

    if persona_habits:
        rows = []
        for persona, mode_strengths in sorted(persona_habits.items()):
            for mode, strengths in mode_strengths.items():
                avg = sum(strengths) / len(strengths)
                rows.append({
                    'Persona': persona.replace('_', ' ').title(),
                    'Mode': mode,
                    'P(stay)': round(avg, 3),
                    'Agents': len(strengths),
                })
        if rows:
            df = pd.DataFrame(rows).sort_values('P(stay)', ascending=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info(
                "No habits formed yet — agents need 3+ consecutive steps "
                "on the same mode. Run more steps to see habit data."
            )
    else:
        # Show all agents even without habits — gives visibility into which
        # personas are present and confirms Markov chains are wired up.
        st.caption(
            "No habits formed yet (need ≥ 3 consecutive uses of same mode). "
            "Showing all agents to confirm Markov chains are active."
        )
        rows = []
        for a in agents:
            s = _markov_summary(a)
            if s is None:
                continue
            rows.append({
                'Persona': getattr(a, 'user_story_id', '?').replace('_', ' ').title(),
                'Agent': a.state.agent_id,
                'Steps recorded': s.get('total_steps', 0),
                'Recent modes': ' → '.join(s.get('mode_history', [])[-3:]) or 'none',
                'Status': '⏳ warming up',
            })
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── 2. Single-agent transition matrix ────────────────────────────────
    st.markdown("#### Transition matrix — inspect one agent")
    story_agents_with_chain = [
        a for a in agents if getattr(a, 'mode_chain', None) is not None
    ]
    if not story_agents_with_chain:
        st.info("No agents with Markov chains found.")
        return

    selected_id = st.selectbox(
        "Select agent", 
        [a.state.agent_id for a in story_agents_with_chain],
        key="markov_agent_select"
    )
    selected = next(
        (a for a in story_agents_with_chain if a.state.agent_id == selected_id),
        None
    )

    if not selected or selected.mode_chain is None:
        return

    chain   = selected.mode_chain
    summary = chain.summary()

    col_info, col_hist = st.columns([2, 3])
    with col_info:
        st.markdown(f"**Persona**: `{summary['persona']}`")
        st.markdown(f"**Steps recorded**: `{summary['total_steps']}`")
        st.markdown(f"**Recent modes**: `{' → '.join(summary['mode_history'])}`")
        habits = summary.get('habits', {})
        if habits:
            st.markdown("**Habit strengths (P(stay))**:")
            for mode, strength in sorted(habits.items(), key=lambda x: -x[1]):
                bar = "█" * int(strength * 12) + "░" * (12 - int(strength * 12))
                lock = " 🔒" if strength > 0.75 else ""
                st.markdown(f"  `{mode:<16}` {bar} {strength:.2f}{lock}")
        else:
            st.caption("No habit data yet (need ≥ 3 consecutive uses of same mode).")

    with col_hist:
        # Show transition matrix as a heatmap for modes with non-zero usage
        # Include modes from: habit_counts, mode_history, and current mode.
        # This ensures the matrix is always populated even when warming up.
        _current_mode = getattr(selected.state, 'mode', '')
        _history_modes = set(summary.get('mode_history', []))
        active_modes = [
            m for m in chain.modes
            if chain.habit_counts.get(m, 0) > 0
            or m == _current_mode
            or m in _history_modes
        ][:10]
 
        # Fallback: if still empty, show the top 5 modes by initial probability
        if not active_modes and chain.modes:
            active_modes = chain.modes[:5]

        if active_modes:
            mode_idx = {m: chain.modes.index(m) for m in active_modes}
            matrix_data = {
                from_m: {
                    to_m: round(chain.T[mode_idx[from_m]][mode_idx[to_m]], 3)
                    for to_m in active_modes
                }
                for from_m in active_modes
            }
            df_matrix = pd.DataFrame(matrix_data).T
            df_matrix.index.name = "from \\ to"

            # Highlight diagonal
            def highlight_diag(val):
                if val > 0.65:
                    return 'background-color: rgba(31,160,90,0.3); font-weight: bold'
                elif val > 0.40:
                    return 'background-color: rgba(31,120,160,0.15)'
                return ''

            st.dataframe(
                df_matrix.style.applymap(highlight_diag),
                use_container_width=True
            )
            st.caption(
                "Rows = from-mode, columns = to-mode. "
                "Green diagonal = strong habit. "
                "Off-diagonal = likely switches."
            )
        else:
            st.caption("No transition data yet — run more simulation steps.")

    with st.expander("How habit formation works (Phase 3 Markov)"):
        st.markdown("""
**Model**: Each `StoryDrivenAgent` has a `PersonalityMarkovChain` initialised 
from their persona type. Initial diagonal values:

| Persona | P(stay) | Interpretation |
|---------|---------|----------------|
| eco_warrior | 0.45 | High switching — seeks greener modes |
| business_commuter | 0.70 | Habit-driven — sticks to what works |
| shift_worker | 0.65 | Moderate lock-in |
| student | 0.50 | Exploratory |

**Update rule** (called every step after satisfaction is computed):
- Satisfaction > 0.7 → P(stay) += 0.04
- Satisfaction < 0.3 → P(stay) -= 0.03
- Consecutive streak > 3 → additional +0.02 × (streak ÷ 3), capped at +0.15

**BDI integration**: `get_prior(current_mode)` returns P(next_mode | current_mode). 
The BDI planner applies a cost discount of up to 15% to modes with high transition 
probability, making habitual modes marginally cheaper without overriding desire weights.

**What to look for**: After 100+ steps, business_commuter agents should show 
P(stay) > 0.75 for their dominant mode (visible as a bright green diagonal cell above). 
eco_warrior agents should show more uniform rows — they keep exploring alternatives.
        """)