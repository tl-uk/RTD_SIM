# RTD_SIM/debug/test_ferry_network_loader.py
"""
Standalone test for ferry network loader.

python test_ferry_network_loader.py

"""

import logging
import sys
import os

# Ensure the simulation module can be imported
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from simulation.spatial.ferry_network import fetch_maritime_graphs

# Configure logger to output directly to the console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_ferry_loader')

def run_ferry_test():
    logger.info("Starting Standalone Ferry Network Loader Test...")

    # Bounding box covering Edinburgh/Firth of Forth and beyond
    # Format: (North, South, East, West)
    test_bbox = (56.50, 55.35, -2.58, -3.95)
    logger.info(f"Using Bounding Box: {test_bbox}")

    try:
        # use_cache=False forces it to hit the Overpass API live
        graphs = fetch_maritime_graphs(
            bbox=test_bbox, 
            city_tag='standalone_test', 
            use_cache=False
        )

        ferry_graph = graphs.get('ferry')

        if ferry_graph and len(ferry_graph.nodes) > 0:
            logger.info("✅ SUCCESS: Ferry graph loaded from Overpass!")
            logger.info(f"Nodes: {ferry_graph.number_of_nodes()}")
            logger.info(f"Edges: {ferry_graph.number_of_edges()}")
            
            # Print a few sample nodes to verify data structure
            logger.info("Sample Terminal Nodes:")
            sample_nodes = list(ferry_graph.nodes(data=True))[:3]
            for n_id, n_data in sample_nodes:
                name = n_data.get('name', 'Unnamed Terminal')
                logger.info(f"  - ID: {n_id} | Name: {name} | Lat: {n_data.get('lat')}, Lon: {n_data.get('lon')}")
                
        else:
            logger.error("❌ FAILED: Ferry graph is None or empty. The Overpass query failed or returned no data.")

    except Exception as e:
        logger.error(f"❌ EXCEPTION raised during fetch: {e}")

if __name__ == "__main__":
    run_ferry_test()