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
        update_interval: int = 5,   # steps between full belief updates
        saturation_history: int = 8, # how many recent satisfaction scores to use
    ):
        self.w_prior  = prior_weight
        self.w_exp    = experience_weight
        self.w_peer   = peer_weight
        self.interval = update_interval
        self.history  = saturation_history
        self._agent_index: dict = {}   # populated on first update call

        assert abs(prior_weight + experience_weight + peer_weight - 1.0) < 1e-6, \
            "Weights must sum to 1.0"

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

        # ── 3. Update beliefs ─────────────────────────────────────────────
        self._update_beliefs(agent, satisfaction_by_mode, peer_ev_rate)

        # ── 4. Re-weight desires from peer observations ───────────────────
        # This replaces the direct agent.state.mode overwrite in the loop,
        # letting social influence flow through the BDI desire weights instead.
        self._reweight_desires_from_peers(agent, peer_ev_rate)

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
            ev_modes = {'ev', 'van_electric', 'truck_electric', 'hgv_electric'}
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

    def _update_beliefs(
        self,
        agent,
        satisfaction_by_mode: Dict[str, List[float]],
        peer_ev_rate: float,
    ) -> None:
        """
        Update belief strengths for all updateable beliefs.

        Belief text is matched to transport modes by keyword. The matched
        mode's recent satisfaction history forms the likelihood term.
        """
        beliefs = getattr(agent.user_story, 'beliefs', [])

        for belief in beliefs:
            if not getattr(belief, 'updateable', True):
                continue

            # Map belief to a mode bucket
            relevant_mode = self._belief_to_mode(belief)
            if relevant_mode is None:
                continue

            prior = float(getattr(belief, 'strength', 0.5))

            # Personal experience likelihood
            scores = satisfaction_by_mode.get(relevant_mode, [])
            if scores:
                recent = scores[-self.history:]
                exp_likelihood = sum(recent) / len(recent)
            else:
                exp_likelihood = prior  # No experience → no pull away from prior

            # Peer likelihood (EV beliefs shift with peer EV adoption)
            ev_modes = {'ev', 'van_electric', 'truck_electric', 'hgv_electric'}
            if relevant_mode in ev_modes:
                peer_likelihood = peer_ev_rate
            else:
                peer_likelihood = prior  # Non-EV beliefs unaffected by EV peer signal

            # Bayesian posterior
            posterior = (
                self.w_prior * prior
                + self.w_exp  * exp_likelihood
                + self.w_peer * peer_likelihood
            )
            posterior = max(0.0, min(1.0, posterior))

            # Only log meaningful shifts
            delta = abs(posterior - prior)
            if delta > 0.05:
                logger.debug(
                    "Belief update %s '%s': %.2f → %.2f (exp=%.2f, peer=%.2f)",
                    agent.state.agent_id,
                    getattr(belief, 'text', '?')[:40],
                    prior, posterior,
                    exp_likelihood, peer_likelihood,
                )

            belief.strength = posterior

    def _reweight_desires_from_peers(
        self, agent, peer_ev_rate: float
    ) -> None:
        """
        Nudge agent's eco desire toward peer EV adoption rate.

        This replaces the direct agent.state.mode = best_mode overwrite
        in the simulation loop's social influence block. Instead of forcing
        a mode switch, we shift the desire weight so the BDI planner
        naturally gravitates toward what peers are doing.

        The nudge is small (≤ 0.03 per update) to preserve individuality.
        """
        if not hasattr(agent, 'desires'):
            return

        eco = agent.desires.get('eco', 0.5)

        # Peer EV rate above 0.5 nudges eco up; below 0.5 nudges it down
        delta = (peer_ev_rate - 0.5) * 0.06   # max ±0.03 per update
        new_eco = max(0.0, min(1.0, eco + delta))

        if abs(new_eco - eco) > 0.001:
            agent.desires['eco'] = new_eco
            logger.debug(
                "Desire re-weight %s: eco %.3f → %.3f (peer_ev=%.2f)",
                agent.state.agent_id, eco, new_eco, peer_ev_rate,
            )

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