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


def _peer_edges(results, max_edges=80):
    """
    Extract (source_id, target_id, weight) edges from SocialNetwork.
    Falls back to empty list if network is not available or doesn't
    expose get_neighbors().
    """
    network = getattr(results, 'network', None)
    if network is None:
        return []

    edges = []
    agents = _story_agents(results)
    seen = set()

    for agent in agents[:40]:   # cap at 40 agents to keep graph readable
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

        # Build node list with metadata
        node_meta = {}
        for a in agents[:40]:
            aid   = a.state.agent_id
            eco   = a.desires.get('eco', 0.5) if hasattr(a, 'desires') else 0.5
            mode  = getattr(a.state, 'mode', 'walk')
            label = aid.rsplit('_', 1)[0]   # strip trailing random seed
            ctx   = getattr(a, 'agent_context', {})
            occ   = ctx.get('charger_occupancy_nearby', None)
            peer_ev = ctx.get('peer_ev_rate', None)
            beliefs = _belief_snapshot(a)
            belief_str = '; '.join(f"{t}: {s}" for t, s in beliefs[:3])

            tooltip = (
                f"<b>{label}</b><br/>"
                f"Mode: {mode}<br/>"
                f"Eco desire: {eco:.2f}<br/>"
                + (f"Charger occupancy: {occ:.0%}<br/>" if occ is not None else "")
                + (f"Peer EV rate: {peer_ev:.0%}<br/>" if peer_ev is not None else "")
                + (f"Beliefs: {belief_str}" if belief_str else "")
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
              "physics": {"stabilization": {"iterations": 80}},
              "nodes": {"shape": "dot", "scaling": {"min": 10, "max": 24}},
              "edges": {"color": {"opacity": 0.4}, "smooth": {"type": "continuous"}},
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
                    label=aid.rsplit('_', 2)[0][-20:],
                    title=meta['tooltip'],
                    color=color,
                    size=12 + eco * 10,
                )

            for e in edges:
                # Only add edges where both endpoints are in the node set.
                # Neighbors outside agents[:40] were never added to pyvis and
                # cause "non existent node" NetworkXError.
                if e['source'] in node_meta and e['target'] in node_meta:
                    net.add_edge(e['source'], e['target'], width=1.0)

            with tempfile.NamedTemporaryFile(
                delete=False, suffix='.html', mode='w'
            ) as f:
                net.save_graph(f.name)
                html_path = f.name

            with open(html_path) as f:
                html_content = f.read()
            os.unlink(html_path)

            st.components.v1.html(html_content, height=500, scrolling=False)

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
    with st.expander("How peer influence flows into BDI (Phase 2)"):
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

    with st.expander("How belief updating works (Phase 2 Bayesian)"):
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
        df = pd.DataFrame(rows).sort_values('P(stay)', ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info(
            "No habit data yet. Habits form after an agent uses the same mode "
            "3+ consecutive times. Run more steps or check that `mode_chain.record_step()` "
            "is being called (requires `config.enable_social = True`)."
        )

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
        active_modes = [
            m for m in chain.modes
            if chain.habit_counts.get(m, 0) > 0
            or getattr(selected.state, 'mode', '') == m
        ][:10]  # cap at 10 for readability

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
