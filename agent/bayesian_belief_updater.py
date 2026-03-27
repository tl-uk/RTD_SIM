"""
agent/bayesian_belief_updater.py

Core Innovation: Bayesian Belief Updating from experience and social signals.

The three gaps identified in _is_mode_feasible(state, context):
  1. Charger occupancy never reaches agent beliefs
  2. Peer mode choices influence agent.state.mode directly (bypasses BDI)
  3. Satisfaction history never feeds back into beliefs

This module closes all three by:
  - Collecting signals from infrastructure, peers, and experience each step
  - Running a lightweight Bayesian update on relevant beliefs
  - Writing outputs into agent_context so BDI planner reads them naturally
  - Letting social influence flow through desire re-weighting (not state overwrite)

Design principles:
  - Stateless updater: BayesianBeliefUpdater holds no per-agent state.
    All state lives in agent.state and agent_context so the simulation loop
    can call it freely without lifecycle management.
  - No numpy dependency: uses only stdlib math for portability.
  - Graceful degradation: every path has a fallback; missing signals = no update.
"""

from __future__ import annotations
import math
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# BAYESIAN UPDATER
# ============================================================================

class BayesianBeliefUpdater:
    """
    Updates agent beliefs based on three signal sources:

      1. Infrastructure perception  — charger occupancy near current location
      2. Personal experience        — recent satisfaction with each mode
      3. Social observation         — what peers are choosing and experiencing

    Each update follows a simplified Bayesian rule:
        posterior = w_prior * prior
                  + w_exp   * likelihood(experience)
                  + w_peer  * likelihood(peer_observations)

    The weights are fixed at construction time and sum to 1.0.
    """

    def __init__(
        self,
        prior_weight: float = 0.50,
        experience_weight: float = 0.35,
        peer_weight: float = 0.15,
        update_interval: int = 5,
        saturation_history: int = 8,
    ):
        self.w_prior  = prior_weight
        self.w_exp    = experience_weight
        self.w_peer   = peer_weight
        self.interval = update_interval
        self.history  = saturation_history
        self._agent_index: dict = {}

        assert abs(prior_weight + experience_weight + peer_weight - 1.0) < 1e-6, \
            "Weights must sum to 1.0"

    # ── Complex Contagion thresholds ──────────────────────────────────────
    # Phase 10c: minimum fraction of neighbours that must have adopted a mode
    # before that mode's belief becomes updateable this step.
    # Freight operators require stronger peer evidence (high financial risk);
    # eco-warriors update with minimal social proof (early adopters).
    _COMPLEX_CONTAGION_THRESHOLDS: Dict[str, float] = {
        'paramedic':               0.60,  # blue-light: near-universal proof required
        'fleet_manager_healthcare':0.50,
        'fleet_manager_logistics': 0.35,
        'fleet_manager_retail':    0.35,
        'port_terminal_operator':  0.40,
        'rail_freight_operator':   0.38,
        'air_freight_operator':    0.38,
        'freight_operator':        0.40,  # high financial risk
        'delivery_driver':         0.20,  # gig: lower barrier
        'shift_worker':            0.25,
        'taxi_driver':             0.35,  # <-- NEW: Needs moderate peer proof
        'ride_hail_driver':        0.25,  # <-- NEW: Faster to adapt to costs
        'emergency_trade_worker':  0.50,  # <-- NEW: High reliability risk
        'rural_technician':        0.45,  # <-- NEW: High range anxiety
        'island_tradesperson':     0.40,  # <-- NEW
        'specialist_engineer':     0.30,  # <-- NEW
        'eco_warrior':             0.10,  # early adopter: minimal proof
        'budget_student':          0.15,
        'business_commuter':       0.30,
        'concerned_parent':        0.25,
        'default':                 0.30,
    }

    # ── Public API ────────────────────────────────────────────────────────
    
    def rebuild_agent_index(self, agents: list) -> None:
        """
        Rebuild the agent_id → agent lookup dict.
 
        Call once after agents are created (in simulation_loop.py,
        just before the main step loop begins).
        """
        self._agent_index = {
            a.state.agent_id: a
            for a in agents
            if hasattr(a, 'state') and hasattr(a.state, 'agent_id')
        }
        logger.debug(
            "BayesianBeliefUpdater: agent index built (%d agents)",
            len(self._agent_index),
        )

    def update_agent(
        self,
        agent,
        step: int,
        infrastructure,               # InfrastructureManager | None
        network,                      # SocialNetwork | None
        satisfaction_by_mode: Dict[str, List[float]],  # mode → [scores]
    ) -> None:
        """
        Main entry point. Call once per agent per update interval.

        Mutates:
          - agent.user_story.beliefs[*].strength   (Bayesian update)
          - agent.agent_context                    (charger_occupancy_nearby,
                                                    peer_ev_rate, etc.)
          - agent.desires                          (peer re-weighting)
        """
        if step % self.interval != 0:
            return

        if not hasattr(agent, 'user_story') or not hasattr(agent, 'agent_context'):
            return

        # ── 1. Infrastructure signal ──────────────────────────────────────
        charger_signal = self._get_charger_signal(agent, infrastructure)
        agent.agent_context['charger_occupancy_nearby'] = charger_signal

        # ── 2. Peer signal ────────────────────────────────────────────────
        # _agent_index is rebuilt on first call or when agent count changes.
        # This avoids calling network.get_agent() which doesn't exist on
        # SocialNetwork — instead we look up agents by ID in a plain dict.
        peer_ev_rate, peer_modes = self._get_peer_signal(
            agent, network, self._agent_index
        )
        agent.agent_context['peer_ev_rate'] = peer_ev_rate
        agent.agent_context['peer_modes']   = peer_modes

        # ── 3. Update beliefs (with Complex Contagion gate) ──────────────
        self._update_beliefs(agent, satisfaction_by_mode, peer_ev_rate)

        # ── 4. Re-weight desires from peer observations ───────────────────
        self._reweight_desires_from_peers(agent, peer_ev_rate)

        # ── 5. Write ev_viability_belief to agent_context ─────────────────
        # The BDI planner reads context['ev_viability_belief'] for the ASI
        # Tier 2 (Shift) check. Without this write the value was always the
        # default 0.5, making the ev_viability_threshold in the CPG have no
        # effect on actual tier selection.
        ev_belief = self._compute_ev_viability_belief(agent, peer_ev_rate)
        agent.agent_context['ev_viability_belief'] = ev_belief

    # ── Signal collection ─────────────────────────────────────────────────

    def _get_charger_signal(
        self, agent, infrastructure
    ) -> float:
        """
        Return occupancy rate [0,1] of the nearest charger to the agent's
        current location. Returns 0.0 if no infrastructure or no location.

        This value is written into agent_context['charger_occupancy_nearby']
        so _is_mode_feasible can read it without touching infrastructure directly.
        """
        if not infrastructure:
            return 0.0

        loc = getattr(agent.state, 'location', None)
        if loc is None:
            return 0.0

        try:
            nearest = infrastructure.find_nearest_charger(
                location=loc, charger_type='any', max_distance_km=3.0
            )
            if not nearest:
                return 0.0

            station_id, _ = nearest
            avail = infrastructure.get_charger_availability(station_id)

            # availability dict has 'occupancy_rate' or we compute it
            if 'occupancy_rate' in avail:
                return float(avail['occupancy_rate'])

            # Fallback: derive from available/total
            total = avail.get('total_ports', 1)
            free  = avail.get('available_ports', total)
            return max(0.0, (total - free) / max(total, 1))

        except Exception as e:
            logger.debug("charger signal failed: %s", e)
            return 0.0

    def _get_peer_signal(
        self, agent, network, agent_index: dict
    ) -> Tuple[float, Dict[str, int]]:
        """
        Return (ev_adoption_rate_among_peers, mode_count_dict).
 
        Uses a pre-built agent_index dict (agent_id → agent) instead of
        calling network.get_agent() which is not implemented on SocialNetwork.
        """
        if not network:
            return 0.0, {}
 
        try:
            agent_id = agent.state.agent_id
            neighbors = network.get_neighbors(agent_id)
            if not neighbors:
                return 0.0, {}
 
            mode_counts: Dict[str, int] = {}
            ev_modes = {'ev', 'van_electric', 'truck_electric', 'hgv_electric', 'taxi_ev'}
            ev_count = 0
 
            for nb_id in neighbors:
                nb = agent_index.get(nb_id)
                if nb is None:
                    continue
                mode = getattr(nb.state, 'mode', 'walk')
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
                if mode in ev_modes:
                    ev_count += 1
 
            total = max(len(neighbors), 1)
            return ev_count / total, mode_counts
 
        except Exception as e:
            logger.debug("peer signal failed: %s", e)
            return 0.0, {}

    # ── Bayesian update ───────────────────────────────────────────────────

    # Helper to map text back to fused_belief keys (Add this above _update_beliefs)
    def _map_belief_text_to_fused_key(self, text: str) -> Optional[str]:
        t = text.lower()
        if any(w in t for w in ('ev', 'electric', 'battery')): return 'ev_is_viable'
        if any(w in t for w in ('transit', 'public transport', 'bus', 'train')): return 'public_transport_reliable'
        if any(w in t for w in ('congestion', 'traffic', 'jam')): return 'congestion_likely'
        if any(w in t for w in ('cost', 'afford', 'price', 'expensive')): return 'cost_pressure_high'
        if any(w in t for w in ('climate', 'carbon', 'emission', 'environment')): return 'climate_urgency'
        if any(w in t for w in ('range', 'anxiety', 'mileage')): return 'range_anxiety'
        if any(w in t for w in ('charger', 'charging', 'infrastructure')): return 'charger_availability'
        return None

    def _update_beliefs(
        self,
        agent,
        satisfaction_by_mode: Dict[str, List[float]],
        peer_ev_rate: float,
    ) -> None:
        """
        Update belief strengths with Complex Contagion gate for EV beliefs.

        Phase 10c — Complex Contagion:
        EV beliefs only update if the fraction of the agent's neighbours
        already using EV modes meets or exceeds the persona-specific threshold.
        This models the high financial risk of freight operators who require
        strong peer evidence before believing EV is viable, vs eco-warriors
        who update with minimal social proof (early adopter behaviour).

        Non-EV beliefs update unconditionally (simple contagion).
        """
        beliefs = getattr(agent.user_story, 'beliefs', [])
        ev_modes = {'ev', 'van_electric', 'truck_electric', 'hgv_electric'}

        # Persona-calibrated threshold for EV belief updates
        persona_id = getattr(agent.user_story, 'id', 'default')
        contagion_threshold = self._COMPLEX_CONTAGION_THRESHOLDS.get(
            persona_id, self._COMPLEX_CONTAGION_THRESHOLDS['default']
        )

        # Pull fused_beliefs from context
        fused_beliefs = agent.agent_context.get('fused_beliefs', {})

        for belief in beliefs:
            if not getattr(belief, 'updateable', True):
                continue

            relevant_mode = self._belief_to_mode(belief)
            if relevant_mode is None:
                continue

            # Use fused belief as the calibrated prior seed if available
            prior = float(getattr(belief, 'strength', 0.5))
            fused_key = self._map_belief_text_to_fused_key(getattr(belief, 'text', ''))
            if fused_key and fused_key in fused_beliefs:
                prior = float(fused_beliefs[fused_key])

            # ── Complex Contagion gate for EV beliefs ─────────────────────
            # EV belief only updates if peer adoption rate >= threshold.
            # This gates the update entirely — the prior is preserved unchanged
            # rather than nudged, modelling the "I'll wait and see" behaviour
            # of risk-averse operators who need multiple peer examples.
            if relevant_mode in ev_modes:
                if peer_ev_rate < contagion_threshold:
                    logger.debug(
                        "Contagion gate CLOSED for %s belief '%s': "
                        "peer_ev=%.2f < threshold=%.2f (persona=%s)",
                        agent.state.agent_id,
                        getattr(belief, 'text', '?')[:30],
                        peer_ev_rate, contagion_threshold, persona_id,
                    )
                    continue  # belief frozen this step
                peer_likelihood = peer_ev_rate
            else:
                peer_likelihood = prior   # non-EV beliefs unaffected by EV peer signal

            # Personal experience likelihood
            scores = satisfaction_by_mode.get(relevant_mode, [])
            exp_likelihood = (
                sum(scores[-self.history:]) / len(scores[-self.history:])
                if scores else prior
            )

            # Bayesian posterior
            posterior = max(0.0, min(1.0,
                self.w_prior * prior
                + self.w_exp  * exp_likelihood
                + self.w_peer * peer_likelihood
            ))

            delta = abs(posterior - prior)
            if delta > 0.05:
                logger.debug(
                    "Belief update %s '%s': %.2f → %.2f (exp=%.2f, peer=%.2f)",
                    agent.state.agent_id,
                    getattr(belief, 'text', '?')[:40],
                    prior, posterior, exp_likelihood, peer_likelihood,
                )

            belief.strength = posterior

    def _reweight_desires_from_peers(
        self, agent, peer_ev_rate: float
    ) -> None:
        """Nudge agent's eco desire toward peer EV adoption rate (max ±0.03)."""
        if not hasattr(agent, 'desires'):
            return

        eco = agent.desires.get('eco', 0.5)
        delta = (peer_ev_rate - 0.5) * 0.06
        new_eco = max(0.0, min(1.0, eco + delta))

        if abs(new_eco - eco) > 0.001:
            agent.desires['eco'] = new_eco
            logger.debug(
                "Desire re-weight %s: eco %.3f → %.3f (peer_ev=%.2f)",
                agent.state.agent_id, eco, new_eco, peer_ev_rate,
            )

    def _compute_ev_viability_belief(
        self, agent, peer_ev_rate: float
    ) -> float:
        """
        Compute a scalar ev_viability_belief [0,1] from EV-related belief strengths.

        This value is written to agent_context['ev_viability_belief'] so the
        BDI planner's ASI Tier 2 (Shift) check reads a real belief signal
        rather than the default 0.5.

        Formula: weighted average of EV-related belief strengths, boosted by
        the peer_ev_rate and capped at 1.0. If no EV beliefs exist, returns
        the peer_ev_rate as a pure social signal.
        """
        ev_keywords = {'ev', 'electric vehicle', 'electric car', 'battery',
                       'cargo', 'freight', 'van', 'truck', 'hgv'}
        ev_strengths = []

        beliefs = getattr(getattr(agent, 'user_story', None), 'beliefs', [])
        for belief in beliefs:
            text = getattr(belief, 'text', '').lower()
            if any(kw in text for kw in ev_keywords):
                ev_strengths.append(float(getattr(belief, 'strength', 0.5)))

        if ev_strengths:
            belief_signal = sum(ev_strengths) / len(ev_strengths)
        else:
            belief_signal = 0.5  # neutral prior when no EV beliefs present

        # Blend belief strength with peer signal — peer evidence matters more
        # at low belief levels (early adoption) and less once belief is strong.
        blended = 0.6 * belief_signal + 0.4 * peer_ev_rate
        return max(0.0, min(1.0, blended))

    # ── Belief → mode mapping ─────────────────────────────────────────────

    _BELIEF_KEYWORDS: List[Tuple[List[str], str]] = [
        (['ev', 'electric vehicle', 'electric car', 'battery'],          'ev'),
        (['bus', 'public transport', 'transit'],                         'bus'),
        (['bike', 'cycling', 'cycle'],                                   'bike'),
        (['walk', 'walking', 'pedestrian'],                              'walk'),
        (['train', 'rail', 'metro'],                                     'local_train'),
        (['car', 'driving', 'vehicle', 'diesel', 'petrol'],              'car'),
        (['scooter', 'e-scooter'],                                       'e_scooter'),
        (['tram'],                                                        'tram'),
        (['cargo', 'freight', 'delivery van', 'van'],                    'van_electric'),
    ]

    def _belief_to_mode(self, belief) -> Optional[str]:
        """Return the mode most relevant to this belief's text, or None."""
        text = getattr(belief, 'text', '').lower()
        for keywords, mode in self._BELIEF_KEYWORDS:
            if any(kw in text for kw in keywords):
                return mode
        return None