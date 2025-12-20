import React, { useState } from 'react';
import { AlertCircle, CheckCircle, Clock, Zap, TrendingUp, Users, DollarSign, Map } from 'lucide-react';

const Phase45Preparation = () => {
  const [selectedPhase, setSelectedPhase] = useState('immediate');

  const phases = {
    immediate: {
      title: "Phase 4.5A: Infrastructure Constraints (NOW - Week 1-2)",
      priority: "CRITICAL",
      duration: "1-2 weeks",
      goal: "Add infrastructure awareness to agent decision-making",
      items: [
        {
          component: "Charging Infrastructure Layer",
          why: "EVs need chargers to be viable",
          what: [
            "Add charging station locations (POI data or manual placement)",
            "Track charger availability (occupied/free)",
            "Define charger types (Level 2, DC fast, home charging)",
            "Add charging time to travel time calculations"
          ],
          implementation: "agent/infrastructure_constraints.py",
          impact: "BDI planner considers charger availability when choosing EV"
        },
        {
          component: "Range Anxiety Model",
          why: "Agents won't choose EVs for trips beyond range",
          what: [
            "Add battery_range_km to vehicle types",
            "Check if trip_distance < battery_range",
            "Apply penalty to EV cost if no charger at destination",
            "Add 'range_concern' desire weight for risk-averse agents"
          ],
          implementation: "agent/bdi_planner.py (cost calculation)",
          impact: "EVs only chosen for feasible trips"
        },
        {
          component: "Infrastructure Capacity Tracking",
          why: "What-if scenarios need to track saturation",
          what: [
            "Track chargers_in_use / total_chargers",
            "Track queue_time at saturated chargers",
            "Add 'charger_congestion' factor to BDI cost",
            "Store infrastructure_metrics in time series"
          ],
          implementation: "simulation/infrastructure_manager.py",
          impact: "Reveals infrastructure bottlenecks"
        },
        {
          component: "Cost Model Enhancement",
          why: "True cost includes infrastructure access",
          what: [
            "Add charging_cost_per_kwh parameter",
            "Add home_charger ownership probability by persona",
            "Calculate total_cost = travel + charging + time_waiting",
            "Add infrastructure_access desire dimension"
          ],
          implementation: "simulation/spatial/metrics_calculator.py",
          impact: "Realistic cost comparison between modes"
        }
      ]
    },
    
    scenario: {
      title: "Phase 4.5B: What-If Scenario Framework (Week 2-3)",
      priority: "HIGH", 
      duration: "1-2 weeks",
      goal: "Enable interactive scenario testing",
      items: [
        {
          component: "Scenario Configuration System",
          why: "Test 'what if everyone goes EV' dynamically",
          what: [
            "Define scenarios: baseline, all_ev, rapid_transition, policy_push",
            "Override agent mode_preferences by scenario",
            "Adjust infrastructure by scenario (e.g., +50% chargers)",
            "Store scenario parameters in YAML"
          ],
          implementation: "simulation/scenarios.yaml + scenario_engine.py",
          impact: "Compare multiple futures side-by-side"
        },
        {
          component: "Policy Intervention Points",
          why: "Inject policies at specific timesteps",
          what: [
            "Add 'policy_events' list: {step: 50, type: 'subsidy', params: {...}}",
            "Implement policy types: subsidy, ban, mandate, infrastructure",
            "Apply policy effects to agent desires or costs",
            "Track policy_adoption_rate over time"
          ],
          implementation: "simulation/policy_injector.py",
          impact: "Test 'EV mandate at step 50' scenarios"
        },
        {
          component: "Comparative Analysis Dashboard",
          why: "Visualize scenario differences",
          what: [
            "Run baseline + scenario in parallel (or sequential)",
            "Plot adoption curves: baseline vs scenario",
            "Show infrastructure utilization difference",
            "Calculate cost_delta (govt + personal + environmental)"
          ],
          implementation: "New tab in streamlit_app.py",
          impact: "Clear visual answers to what-if questions"
        }
      ]
    },
    
    grid: {
      title: "Phase 4.5C: Grid Integration (Week 3-4)",
      priority: "MEDIUM",
      duration: "1-2 weeks", 
      goal: "Model grid impact of EV charging",
      items: [
        {
          component: "Time-of-Day Charging Patterns",
          why: "EVs charge at specific times (evening peak = problem)",
          what: [
            "Add time_of_day to simulation (hour of day)",
            "Define charging_preference_hours by persona/job",
            "Track grid_load_by_hour across all charging EVs",
            "Identify peak_load_hours for grid stress"
          ],
          implementation: "simulation/temporal_patterns.py",
          impact: "Reveals when grid upgrades needed"
        },
        {
          component: "Grid Capacity Constraints",
          why: "Grid has limits - what happens at saturation?",
          what: [
            "Define grid_capacity_mw for region",
            "Sum charging_load_mw from all EVs",
            "If load > capacity: apply brown_out_penalty to agents",
            "Or implement queuing: 'charge after 2am'",
            "Track grid_stress_factor over time"
          ],
          implementation: "simulation/grid_manager.py",
          impact: "Shows when grid upgrades essential"
        },
        {
          component: "Smart Charging Optimization",
          why: "Policy tool: spread charging to off-peak",
          what: [
            "Add policy: smart_charging_incentive",
            "Agents with high 'cost' desire shift to off-peak",
            "Reduce charging cost by 50% for off-peak hours",
            "Track adoption of smart charging behavior"
          ],
          implementation: "agent/charging_behavior.py",
          impact: "Test if pricing flattens grid load"
        },
        {
          component: "Renewable Integration",
          why: "EVs only green if grid is green",
          what: [
            "Add renewable_energy_fraction by hour (solar peaks noon)",
            "Calculate true_emissions = grid_carbon_intensity × kwh_used",
            "Show that night charging = dirtier than day",
            "Track cumulative_carbon_savings vs fossil fleet"
          ],
          implementation: "simulation/carbon_accounting.py",
          impact: "Realistic environmental impact assessment"
        }
      ]
    },
    
    multimodal: {
      title: "Phase 4.5D: Multi-Stakeholder Complexity (Week 4-5)",
      priority: "MEDIUM",
      duration: "1-2 weeks",
      goal: "Model freight, emergency, business impacts",
      items: [
        {
          component: "Freight-Specific Constraints",
          why: "Delivery vans have different needs than cars",
          what: [
            "Add vehicle_class: personal, light_commercial, heavy_freight",
            "Heavy freight: longer range, more charging time, depot charging",
            "Add depot locations to infrastructure",
            "Track delivery_time_impact of charging delays"
          ],
          implementation: "agent/freight_constraints.py",
          impact: "Shows logistics sector bottlenecks"
        },
        {
          component: "Emergency Services Priority",
          why: "Ambulances can't wait for chargers",
          what: [
            "Add agent_priority: emergency > business > personal",
            "Emergency agents jump charger queues",
            "Or maintain fossil backup fleet for emergencies",
            "Track emergency_response_time impact"
          ],
          implementation: "agent/priority_routing.py",
          impact: "Identifies safety-critical gaps"
        },
        {
          component: "Business Cost-Benefit Analysis",
          why: "Companies need ROI calculations",
          what: [
            "Track fleet_transition_cost for businesses",
            "Calculate fuel_savings vs capital_expenditure",
            "Add 'payback_period' metric",
            "Model business_adoption based on economics"
          ],
          implementation: "agent/business_economics.py",
          impact: "Realistic commercial transition timelines"
        },
        {
          component: "Equity Analysis",
          why: "Not everyone can afford EVs or home chargers",
          what: [
            "Track adoption_by_income_bracket",
            "Show that low-income relies on public charging",
            "Calculate public_charger_demand by neighborhood",
            "Identify equity gaps in infrastructure"
          ],
          implementation: "analysis/equity_metrics.py",
          impact: "Reveals who gets left behind"
        }
      ]
    }
  };

  const urgency = [
    {
      title: "Why Do This NOW (Before Phase 5)?",
      reasons: [
        {
          point: "Phase 5 is about REAL-TIME feedback",
          detail: "If infrastructure isn't modeled, real-time adjustments are meaningless"
        },
        {
          point: "What-if analysis needs constraints",
          detail: "Without chargers/grid/costs, 'everyone goes EV' is just fantasy, not policy"
        },
        {
          point: "Data structures must be ready",
          detail: "Phase 5 MQTT/Kalman assumes infrastructure metrics are already tracked"
        },
        {
          point: "Papers need realistic scenarios",
          detail: "Paper 1 (methodology) should include infrastructure-aware BDI model"
        },
        {
          point: "Cascades become meaningful",
          detail: "Social influence → infrastructure saturation → behavior change (real feedback loop)"
        }
      ]
    }
  ];

  const coreDataStructures = [
    {
      title: "Infrastructure Registry",
      code: `# simulation/infrastructure_registry.py
@dataclass
class ChargingStation:
    station_id: str
    location: Tuple[float, float]
    charger_type: str  # 'level2', 'dcfast', 'home'
    num_ports: int
    power_kw: float
    cost_per_kwh: float
    currently_occupied: int = 0
    queue: List[str] = field(default_factory=list)
    
class InfrastructureRegistry:
    def __init__(self):
        self.charging_stations: Dict[str, ChargingStation] = {}
        self.depots: Dict[str, Depot] = {}
        self.grid_capacity_mw: float = 1000.0
        
    def find_nearest_charger(self, location, charger_type='any'):
        # Returns nearest available charger
        pass
        
    def check_availability(self, station_id):
        # Returns True if charger free
        pass
        
    def reserve_charger(self, agent_id, station_id, duration_min):
        # Queue agent for charging
        pass`,
      why: "Central source of truth for infrastructure state"
    },
    {
      title: "Enhanced BDI Cost",
      code: `# In bdi_planner.py cost() method
def cost(self, action: Action, env, state, desires):
    # ... existing metrics ...
    
    # NEW: Infrastructure constraints
    if mode == 'ev':
        # Range feasibility
        if route_distance > MAX_EV_RANGE_KM:
            total_cost += 10.0  # Infeasible
        
        # Charger availability
        dest_charger = env.infrastructure.find_nearest_charger(dest)
        if dest_charger is None:
            total_cost += desires.get('range_anxiety', 0.3) * 2.0
        elif dest_charger.currently_occupied >= dest_charger.num_ports:
            wait_time = estimate_queue_time(dest_charger)
            total_cost += w_time * (wait_time / 60.0)
        
        # Charging cost
        charging_cost = estimate_charging_cost(route_distance, dest_charger)
        total_cost += w_cost * (charging_cost / 5.0)
    
    return total_cost`,
      why: "Makes EV choice realistic, not just preference"
    },
    {
      title: "Scenario Runner",
      code: `# simulation/scenario_runner.py
class ScenarioRunner:
    def run_scenario(self, scenario_config):
        # Load scenario parameters
        params = load_scenario_yaml(scenario_config)
        
        # Override agent generation
        if params.mode_override:
            # Force X% to prefer EVs
            apply_mode_bias(agents, params.ev_preference_boost)
        
        # Override infrastructure
        if params.infrastructure_scale:
            # Add 2x chargers
            multiply_infrastructure(env, params.charger_multiplier)
        
        # Inject policies at timesteps
        for policy in params.policy_timeline:
            schedule_policy(policy.step, policy.type, policy.params)
        
        # Run simulation
        results = run_simulation(...)
        
        return results
    
    def compare_scenarios(self, baseline, scenarios):
        # Run all scenarios
        # Generate comparison plots
        # Calculate cost deltas
        pass`,
      why: "Enables systematic what-if exploration"
    }
  ];

  return (
    <div className="w-full max-w-7xl mx-auto p-6 bg-gradient-to-br from-gray-50 to-blue-50">
      <div className="mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-3">
          🔌 Phase 4.5: Infrastructure-Aware What-If Analysis
        </h1>
        <p className="text-lg text-gray-600">
          Foundation for realistic EV transition scenarios before Phase 5 real-time integration
        </p>
      </div>

      {/* Urgency Panel */}
      <div className="bg-red-50 border-l-4 border-red-500 p-6 mb-6 rounded-r-lg">
        <div className="flex items-start">
          <AlertCircle className="w-6 h-6 text-red-600 mr-3 mt-1 flex-shrink-0" />
          <div>
            <h3 className="text-red-900 font-bold text-lg mb-3">
              Why Implement Infrastructure NOW (Before Phase 5)?
            </h3>
            <div className="space-y-2">
              {urgency[0].reasons.map((reason, idx) => (
                <div key={idx} className="flex items-start">
                  <div className="w-2 h-2 bg-red-500 rounded-full mt-2 mr-3 flex-shrink-0"></div>
                  <div>
                    <span className="font-semibold text-red-900">{reason.point}:</span>
                    <span className="text-red-800 ml-2">{reason.detail}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Phase Selector */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {Object.entries(phases).map(([key, phase]) => (
          <button
            key={key}
            onClick={() => setSelectedPhase(key)}
            className={`p-4 rounded-lg border-2 transition-all text-left ${
              selectedPhase === key
                ? 'border-blue-500 bg-blue-50 shadow-md'
                : 'border-gray-300 bg-white hover:border-blue-300'
            }`}
          >
            <div className="font-bold text-sm text-gray-900 mb-1">{phase.title.split(':')[0]}</div>
            <div className={`text-xs font-semibold ${
              phase.priority === 'CRITICAL' ? 'text-red-600' : 
              phase.priority === 'HIGH' ? 'text-orange-600' : 'text-blue-600'
            }`}>
              {phase.priority} • {phase.duration}
            </div>
          </button>
        ))}
      </div>

      {/* Selected Phase Details */}
      <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">{phases[selectedPhase].title}</h2>
            <p className="text-gray-600 mt-2">{phases[selectedPhase].goal}</p>
          </div>
          <span className={`px-4 py-2 rounded-full text-sm font-bold ${
            phases[selectedPhase].priority === 'CRITICAL' ? 'bg-red-500 text-white' :
            phases[selectedPhase].priority === 'HIGH' ? 'bg-orange-500 text-white' :
            'bg-blue-500 text-white'
          }`}>
            {phases[selectedPhase].priority}
          </span>
        </div>

        <div className="space-y-6">
          {phases[selectedPhase].items.map((item, idx) => (
            <div key={idx} className="border-l-4 border-blue-500 pl-4 py-2 bg-blue-50 rounded-r-lg">
              <h3 className="text-lg font-bold text-blue-900 mb-2">
                {idx + 1}. {item.component}
              </h3>
              
              <div className="bg-white rounded p-3 mb-3">
                <div className="text-sm font-semibold text-blue-800 mb-1">Why:</div>
                <div className="text-sm text-gray-700">{item.why}</div>
              </div>

              <div className="bg-white rounded p-3 mb-3">
                <div className="text-sm font-semibold text-blue-800 mb-2">What to implement:</div>
                <ul className="space-y-1">
                  {item.what.map((task, tidx) => (
                    <li key={tidx} className="text-sm text-gray-700 flex items-start">
                      <CheckCircle className="w-4 h-4 text-green-500 mr-2 mt-0.5 flex-shrink-0" />
                      {task}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="flex items-center justify-between bg-green-50 rounded p-3">
                <div>
                  <div className="text-xs font-semibold text-green-800">Implementation:</div>
                  <code className="text-xs text-green-700">{item.implementation}</code>
                </div>
                <div className="text-right">
                  <div className="text-xs font-semibold text-green-800">Impact:</div>
                  <div className="text-xs text-green-700">{item.impact}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Core Data Structures */}
      <div className="bg-white rounded-xl shadow-lg p-6">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">
          💾 Core Data Structures to Implement
        </h2>
        
        {coreDataStructures.map((struct, idx) => (
          <div key={idx} className="mb-6 last:mb-0">
            <h3 className="text-lg font-bold text-gray-800 mb-2">{struct.title}</h3>
            <div className="bg-gray-900 rounded-lg p-4 mb-2">
              <pre className="text-sm text-green-400 overflow-x-auto">
                <code>{struct.code}</code>
              </pre>
            </div>
            <div className="text-sm text-gray-600 italic">💡 {struct.why}</div>
          </div>
        ))}
      </div>

      {/* Implementation Priority */}
      <div className="mt-6 bg-gradient-to-r from-blue-50 to-purple-50 rounded-xl p-6">
        <h3 className="text-xl font-bold text-gray-900 mb-4">🎯 Recommended Implementation Order</h3>
        <div className="space-y-3">
          <div className="flex items-center gap-3 bg-white rounded-lg p-4">
            <div className="w-8 h-8 bg-red-500 text-white rounded-full flex items-center justify-center font-bold">1</div>
            <div className="flex-1">
              <div className="font-bold">Infrastructure Layer + Range Model</div>
              <div className="text-sm text-gray-600">Week 1 • Enables realistic EV decisions</div>
            </div>
          </div>
          <div className="flex items-center gap-3 bg-white rounded-lg p-4">
            <div className="w-8 h-8 bg-orange-500 text-white rounded-full flex items-center justify-center font-bold">2</div>
            <div className="flex-1">
              <div className="font-bold">Scenario Framework + Policy Injection</div>
              <div className="text-sm text-gray-600">Week 2 • Enables what-if testing</div>
            </div>
          </div>
          <div className="flex items-center gap-3 bg-white rounded-lg p-4">
            <div className="w-8 h-8 bg-yellow-500 text-white rounded-full flex items-center justify-center font-bold">3</div>
            <div className="flex-1">
              <div className="font-bold">Grid Integration + Time-of-Day</div>
              <div className="text-sm text-gray-600">Week 3 • Reveals grid stress</div>
            </div>
          </div>
          <div className="flex items-center gap-3 bg-white rounded-lg p-4">
            <div className="w-8 h-8 bg-blue-500 text-white rounded-full flex-is-center justify-center font-bold">4</div>
            <div className="flex-1">
              <div className="font-bold">Multi-Stakeholder Complexity</div>
              <div className="text-sm text-gray-600">Week 4 • Complete realism</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Phase45Preparation;