# scripts/split_job_contexts.py
"""
Split job_contexts.yaml into categorized files.
Run once to migrate from single file to directory structure.
"""

import yaml
from pathlib import Path

def split_job_contexts():
    """Split job_contexts.yaml into category files."""
    
    # Load existing file
    job_file = Path('agent/job_contexts.yaml')
    with open(job_file, 'r') as f:
        all_jobs = yaml.safe_load(f)
    
    # Define categories
    categories = {
        'micro_delivery': [
            'urban_food_delivery',
            'urban_parcel_delivery',
            'gig_economy_delivery',
        ],
        'light_commercial': [
            'service_engineer_call',
            'trades_contractor',
            'freight_delivery_route',
        ],
        'medium_freight': [
            'regional_distribution',
            'furniture_delivery',
            'construction_materials',
            'refrigerated_transport',
            'waste_collection',
        ],
        'heavy_freight': [
            'long_haul_freight',
            'port_to_warehouse',
            'supermarket_supply',
            'manufacturing_supply_chain',
        ],
        'passenger': [
            'morning_commute',
            'commute_flexible',
            'shopping_trip',
        ],
        'multimodal': [
            'intercity_train_commute',
            'island_ferry_trip',
            'business_flight',
            'accessible_tram_journey',
            'tourist_scenic_rail',
            'last_mile_scooter',
            'multi_modal_commute',
        ]
    }
    
    # Create output directory
    output_dir = Path('agent/job_contexts')
    output_dir.mkdir(exist_ok=True)
    
    # Split jobs by category
    for category, job_ids in categories.items():
        category_jobs = {}
        
        for job_id in job_ids:
            if job_id in all_jobs:
                category_jobs[job_id] = all_jobs[job_id]
        
        if category_jobs:
            output_file = output_dir / f'{category}.yaml'
            with open(output_file, 'w') as f:
                yaml.dump(category_jobs, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            
            print(f"✅ Created {output_file.name} ({len(category_jobs)} jobs)")
    
    # Backup original
    backup_file = Path('agent/job_contexts.yaml.backup')
    job_file.rename(backup_file)
    print(f"\n📦 Original file backed up to {backup_file.name}")
    print(f"🎯 Created {len(categories)} category files in agent/job_contexts/")

if __name__ == '__main__':
    split_job_contexts()