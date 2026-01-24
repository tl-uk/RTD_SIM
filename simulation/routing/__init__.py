"""
Routing subsystem for RTD_SIM.

Route diversity strategies and alternative routing algorithms.
"""

def __getattr__(name):
    if name == 'apply_route_diversity':
        from simulation.routing.route_diversity import apply_route_diversity
        return apply_route_diversity
    elif name == 'add_route_diversity_perturbed':
        from simulation.routing.route_diversity import add_route_diversity_perturbed
        return add_route_diversity_perturbed
    elif name == 'add_route_diversity_k_shortest':
        from simulation.routing.route_diversity import add_route_diversity_k_shortest
        return add_route_diversity_k_shortest
    elif name == 'add_route_diversity_ultra_fast':
        from simulation.routing.route_diversity import add_route_diversity_ultra_fast
        return add_route_diversity_ultra_fast
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    'apply_route_diversity',
    'add_route_diversity_perturbed',
    'add_route_diversity_k_shortest',
    'add_route_diversity_ultra_fast'
]