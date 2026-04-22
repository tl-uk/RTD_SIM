#!/usr/bin/env python3
"""
debug/test_air_network_loader.py

run: python debug/test_air_network_loader.py
"""


import logging
import sys
import os
import traceback

# Ensure the simulation module can be imported
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# NOTE: Adjust this import to match the exact function name in your air_network.py
# try:
from simulation.spatial.air_network import get_or_build_airport_graph, log_air_summary
# except ImportError:
    # pass # Will be handled by the user

# Configure logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_air_loader')

def run_air_test():
    logger.info("Starting Standalone Air Network Loader Test...")
    
    # Bounding box extracted from your log
    test_bbox = (-6.449, 52.854, -0.079, 58.995)
    logger.info(f"Using Bounding Box: {test_bbox}")

    try:
        # NOTE: Change 'fetch_air_networks' to whatever your function is named!
        # use_cache=False forces it to process the JSON from the live API
        # from simulation.spatial.air_network import get_or_build_airport_graph, log_air_summary
        
        graphs = get_or_build_airport_graph(bbox=test_bbox, use_cache=False)
        log_air_summary(graphs) # This will print a summary of the loaded air network to the console
        
        if graphs:
            logger.info("✅ SUCCESS: Air graph loaded without crashing!")
        else:
            logger.warning("⚠️ Fetch function completed, but returned empty graphs.")

    except Exception as e:
        logger.error(f"❌ CRASH DETECTED: {e}")
        logger.info("-" * 40)
        logger.info("TRACEBACK (Look for the line number in air_network.py):")
        traceback.print_exc()
        logger.info("-" * 40)

if __name__ == "__main__":
    run_air_test()