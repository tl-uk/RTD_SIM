"""
agent/job_templates.py

Programmatic job story generation for repetitive patterns.
Strategy 3: Generate freight variations from templates.
"""

from typing import Dict, List, Any


def generate_freight_delivery_variations() -> Dict[str, Any]:
    """
    Generate freight delivery job variations.
    
    Pattern: Same job structure, different vehicle types.
    Example: "Van delivery to stores" vs "Truck delivery to stores"
    """
    
    vehicle_types = {
        'van': {
            'vehicle_type': 'commercial',
            'typical_distance_km': [20, 150],
            'vehicle_constraints': {
                'type': 'light_freight',
                'capacity_kg': [500, 3500],
                'max_range_km': 200,
                'preferred_modes': ['van_electric', 'van_diesel']
            }
        },
        'truck': {
            'vehicle_type': 'medium_freight',
            'typical_distance_km': [50, 300],
            'vehicle_constraints': {
                'type': 'medium_freight',
                'capacity_kg': [5000, 15000],
                'max_range_km': 300,
                'preferred_modes': ['truck_electric', 'truck_diesel']
            }
        },
        'hgv': {
            'vehicle_type': 'heavy_freight',
            'typical_distance_km': [100, 800],
            'vehicle_constraints': {
                'type': 'heavy_freight',
                'capacity_kg': [20000, 44000],
                'max_range_km': 800,
                'preferred_modes': ['hgv_diesel', 'hgv_electric', 'hgv_hydrogen']
            }
        }
    }
    
    # Delivery patterns (same logic, different vehicles)
    delivery_patterns = {
        'retail_delivery': {
            'context': 'When delivering goods to retail stores',
            'goal': 'I want efficient multi-stop routes',
            'outcome': 'So I complete deliveries on schedule',
            'delivery_params': {
                'num_stops': [3, 10],
                'stop_duration_min': [15, 45],
                'route_optimization': 'time_then_cost'
            },
            'destination_type': 'retail'
        },
        'warehouse_transfer': {
            'context': 'When transferring goods between warehouses',
            'goal': 'I want reliable point-to-point delivery',
            'outcome': 'So inventory arrives on schedule',
            'delivery_params': {
                'num_stops': [1, 2],
                'stop_duration_min': [30, 90],
                'route_optimization': 'minimize_time'
            },
            'destination_type': 'warehouse'
        },
        'construction_delivery': {
            'context': 'When delivering materials to construction sites',
            'goal': 'I want reliable delivery that doesn\'t delay projects',
            'outcome': 'So construction schedules are maintained',
            'delivery_params': {
                'num_stops': [1, 3],
                'stop_duration_min': [30, 120],
                'route_optimization': 'reliability_first'
            },
            'destination_type': 'construction_site'
        }
    }
    
    # Generate all combinations
    generated_jobs = {}
    
    for vehicle_name, vehicle_config in vehicle_types.items():
        for pattern_name, pattern in delivery_patterns.items():
            job_id = f'{vehicle_name}_{pattern_name}_generated'
            
            generated_jobs[job_id] = {
                'context': pattern['context'] + f' using {vehicle_name}',
                'goal': pattern['goal'],
                'outcome': pattern['outcome'],
                'job_type': 'freight',
                'delivery_params': pattern['delivery_params'],
                'destination_type': pattern['destination_type'],
                'typical_distance_km': vehicle_config['typical_distance_km'],
                'parameters': {
                    'vehicle_required': True,
                    'cargo_capacity': True,
                    'vehicle_type': vehicle_config['vehicle_type'],
                    'recurring': True,
                    'urgency': 'medium'
                },
                'vehicle_constraints': vehicle_config['vehicle_constraints'],
                'time_window': {
                    'start': '06:00',
                    'end': '18:00',
                    'flexibility': 'medium'
                },
                'plan_context': [
                    f'{vehicle_name.upper()} delivery with time constraints',
                    'Route optimization for fuel efficiency',
                    'Loading dock scheduling required'
                ],
                'csv_columns': {
                    'required': ['depot_lat', 'depot_lon', 'dest_lat', 'dest_lon'],
                    'optional': ['delivery_window', 'cargo_weight']
                }
            }
    
    return generated_jobs

# Additional generation function for time-sensitive delivery variations, demonstrating 
# how we can create multiple job stories with different time windows and urgency levels 
# while keeping the core delivery task consistent. This allows us to test how the agent 
# handles tasks with varying temporal constraints and priorities, which is common in 
# real-world delivery scenarios.
def generate_time_window_variations() -> Dict[str, Any]:
    """
    Generate time-sensitive delivery variations.
    
    Pattern: Same route, different time windows (morning/afternoon/night).
    """
    
    time_windows = {
        'morning': {'start': '06:00', 'end': '12:00', 'urgency': 'high'},
        'afternoon': {'start': '12:00', 'end': '18:00', 'urgency': 'medium'},
        'night': {'start': '18:00', 'end': '02:00', 'urgency': 'low'}
    }
    
    base_job = {
        'context': 'When delivering parcels in urban area',
        'goal': 'I want to complete deliveries within time window',
        'outcome': 'So customer satisfaction is maintained',
        'job_type': 'delivery',
        'destination_type': 'multiple_urban',
        'typical_distance_km': [10, 30],
        'parameters': {
            'vehicle_required': True,
            'cargo_capacity': True,
            'vehicle_type': 'commercial',
            'recurring': True
        },
        'vehicle_constraints': {
            'type': 'light_freight',
            'preferred_modes': ['van_electric', 'van_diesel']
        }
    }
    
    generated = {} # Generate variations for each time window
    
    for time_name, time_config in time_windows.items():
        job_id = f'urban_delivery_{time_name}_generated'
        
        generated[job_id] = {
            **base_job,
            'context': base_job['context'] + f' during {time_name} shift',
            'time_window': {
                'start': time_config['start'],
                'end': time_config['end'],
                'flexibility': 'low'
            },
            'parameters': {
                **base_job['parameters'],
                'urgency': time_config['urgency']
            }
        }
    
    return generated

# Master function to generate all job templates, combining different generation strategies.
def generate_all_job_templates() -> Dict[str, Any]:
    """
    Generate all programmatic job variations.
    
    Returns:
        Dict of job_id -> job_definition
    """
    all_generated = {}
    
    # Add all generation functions
    all_generated.update(generate_freight_delivery_variations())
    all_generated.update(generate_time_window_variations())
    
    return all_generated