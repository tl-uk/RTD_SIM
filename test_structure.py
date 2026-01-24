# test_structure.py
print("Testing module structure...")

# Should work
from simulation.spatial import Router, GraphManager
print("✅ spatial imports work")

# Should work
from simulation.routing import apply_route_diversity
print("✅ routing imports work")

# Should fail (no longer exists)
try:
    from simulation.spatial import route_diversity
    print("❌ ERROR: duplicate route_diversity still exists!")
except (ImportError, AttributeError):
    print("✅ duplicate route_diversity correctly removed")