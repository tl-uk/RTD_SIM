"""
debug/debug_walk_agents.py

Diagnostic tool to trace why agents with vehicle_required=True end up walking.
Add this to agent_creation.py after agent._maybe_plan(env)
"""

import logging
from typing import List, Any, Dict
from simulation.spatial.coordinate_utils import haversine_km

logger = logging.getLogger(__name__)


def diagnose_walk_agent(agent: Any, env: Any, origin, dest) -> Dict:
    """
    Deep diagnostic for agents that shouldn't be walking.
    
    Args:
        agent: StoryDrivenAgent instance
        env: SpatialEnvironment instance
        origin: Origin coordinates
        dest: Destination coordinates
    
    Returns:
        Dict with diagnostic results
    """
    context = getattr(agent, 'agent_context', {})
    
    diagnosis = {
        'agent_id': agent.state.agent_id,
        'mode': agent.state.mode,
        'distance_km': agent.state.distance_km,
        'route_length': len(agent.state.route) if agent.state.route else 0,
        'context': context,
        'issues': []
    }
    
    # Check 1: Origin-destination distance
    od_distance = haversine_km(origin, dest)
    diagnosis['od_distance_km'] = od_distance
    
    if od_distance < 0.5:
        diagnosis['issues'].append(f"Very short trip ({od_distance:.2f}km) - may be too close for vehicles")
    
    # Check 2: Context extraction
    vehicle_required = context.get('vehicle_required', False)
    vehicle_type = context.get('vehicle_type', 'unknown')
    
    if vehicle_required and agent.state.mode == 'walk':
        diagnosis['issues'].append(f"CRITICAL: vehicle_required=True but mode=walk!")
    
    # Check 3: Test manual routing for expected mode
    if vehicle_type == 'micro_mobility':
        test_mode = 'cargo_bike'
    elif vehicle_type == 'heavy_freight':
        test_mode = 'hgv_diesel'
    elif vehicle_type == 'medium_freight':
        test_mode = 'truck_diesel'
    elif vehicle_type == 'commercial':
        test_mode = 'van_diesel'
    else:
        test_mode = 'car'
    
    try:
        test_route = env.compute_route(
            agent_id=f"{agent.state.agent_id}_test",
            origin=origin,
            dest=dest,
            mode=test_mode
        )
        
        if test_route and len(test_route) > 1:
            from simulation.spatial.coordinate_utils import route_distance_km
            test_distance = route_distance_km(test_route)
            diagnosis['manual_route_test'] = {
                'mode': test_mode,
                'success': True,
                'points': len(test_route),
                'distance_km': test_distance
            }
            
            if test_distance > 0:
                diagnosis['issues'].append(f"Manual {test_mode} route works ({test_distance:.1f}km) but agent chose walk!")
        else:
            diagnosis['manual_route_test'] = {
                'mode': test_mode,
                'success': False,
                'points': len(test_route) if test_route else 0
            }
            diagnosis['issues'].append(f"Manual {test_mode} routing FAILED - network issue")
    
    except Exception as e:
        diagnosis['manual_route_test'] = {
            'mode': test_mode,
            'success': False,
            'error': str(e)
        }
        diagnosis['issues'].append(f"Manual routing error: {e}")
    
    # Check 4: Job story distance expectations
    if hasattr(agent, 'job_story') and hasattr(agent.job_story, 'parameters'):
        params = agent.job_story.parameters
        typical_distance = params.get('typical_distance_km')
        
        if typical_distance:
            diagnosis['expected_distance_km'] = typical_distance
            
            if od_distance < typical_distance * 0.3:
                diagnosis['issues'].append(
                    f"Trip {od_distance:.1f}km << expected {typical_distance}km - "
                    f"job story may have unrealistic min distance"
                )
    
    # Check 5: BDI planner mode filtering
    if hasattr(agent, 'planner'):
        try:
            # Get modes that would be offered
            from agent.bdi_planner import BDIPlanner
            planner: BDIPlanner = agent.planner
            
            offered_modes = planner._filter_modes_by_context(context, od_distance)
            diagnosis['offered_modes'] = offered_modes
            
            if 'walk' in offered_modes and len(offered_modes) == 1:
                diagnosis['issues'].append("BDI planner offered ONLY walk - mode filtering broken!")
            elif 'walk' not in offered_modes and agent.state.mode == 'walk':
                diagnosis['issues'].append("Walk not offered but agent chose it - routing failure?")
        
        except Exception as e:
            diagnosis['issues'].append(f"BDI inspection error: {e}")
    
    return diagnosis


def log_walk_agent_diagnostics(agents: List[Any], env: Any):
    """
    Run diagnostics on all agents and log problem cases.
    
    Args:
        agents: List of all agents
        env: SpatialEnvironment instance
    """
    walk_agents = [a for a in agents if a.state.mode == 'walk']
    problem_agents = [
        a for a in walk_agents 
        if getattr(a, 'agent_context', {}).get('vehicle_required', False)
    ]
    
    logger.info(f"   WALK AGENT DIAGNOSTICS")
    logger.info(f"   Total agents: {len(agents)}")
    logger.info(f"   Walking: {len(walk_agents)} ({len(walk_agents)/len(agents)*100:.1f}%)")
    logger.info(f"   PROBLEM (vehicle_required=True): {len(problem_agents)}")
    
    if not problem_agents:
        logger.info(f"âœ… No problem walk agents detected!")
        return
    
    logger.error(f"âŒ Found {len(problem_agents)} agents with vehicle_required=True but mode=walk")
    
    for i, agent in enumerate(problem_agents[:5], 1):  # Show first 5
        logger.error(f"\n--- PROBLEM AGENT {i}/{len(problem_agents)} ---")
        
        diagnosis = diagnose_walk_agent(
            agent, 
            env,
            origin=agent.origin if hasattr(agent, 'origin') else agent.state.location,
            dest=agent.dest if hasattr(agent, 'dest') else agent.state.destination
        )
        
        logger.error(f"Agent ID: {diagnosis['agent_id']}")
        logger.error(f"Mode: {diagnosis['mode']}, Distance: {diagnosis['distance_km']:.1f}km")
        logger.error(f"Route points: {diagnosis['route_length']}")
        logger.error(f"OD distance: {diagnosis['od_distance_km']:.1f}km")
        logger.error(f"Context: {diagnosis['context']}")
        
        if 'offered_modes' in diagnosis:
            logger.error(f"Modes offered by BDI: {diagnosis['offered_modes']}")
        
        if 'manual_route_test' in diagnosis:
            test = diagnosis['manual_route_test']
            if test['success']:
                logger.error(f"Manual {test['mode']} test: âœ… SUCCESS ({test['distance_km']:.1f}km, {test['points']} points)")
            else:
                logger.error(f"Manual {test['mode']} test: âŒ FAILED")
        
        if diagnosis['issues']:
            logger.error(f"Issues detected:")
            for issue in diagnosis['issues']:
                logger.error(f"  - {issue}")
    
    # Summary of root causes
    logger.error(f"\n=== ROOT CAUSE SUMMARY ===")
    
    all_issues = []
    for agent in problem_agents:
        diagnosis = diagnose_walk_agent(
            agent, env,
            origin=agent.origin if hasattr(agent, 'origin') else agent.state.location,
            dest=agent.dest if hasattr(agent, 'dest') else agent.state.destination
        )
        all_issues.extend(diagnosis['issues'])
    
    # Count issue types
    issue_counts = {}
    for issue in all_issues:
        # Categorize by first few words
        category = ' '.join(issue.split()[:5])
        issue_counts[category] = issue_counts.get(category, 0) + 1
    
    for category, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True):
        logger.error(f"  {count}x: {category}...")