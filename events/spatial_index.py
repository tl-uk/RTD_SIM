"""
events/spatial_index.py

R-tree spatial index for efficient radius queries.
Enables O(log N) agent lookup instead of O(N) brute force.

Phase 6.2: Spatial Indexing
"""

from typing import List, Tuple, Dict, Any, Optional
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import rtree, provide fallback
try:
    from rtree import index as rtree_index
    RTREE_AVAILABLE = True
except ImportError:
    RTREE_AVAILABLE = False
    logger.warning(
        "⚠️ rtree not installed. Spatial queries will use O(N) brute force. "
        "Install with: pip install rtree"
    )


@dataclass
class SpatialObject:
    """Object with spatial location and metadata."""
    object_id: str
    latitude: float
    longitude: float
    metadata: Dict[str, Any]


class SpatialIndex:
    """
    Spatial index for efficient radius queries.
    
    Uses R-tree when available, falls back to brute force.
    Optimizes agent perception queries from O(N) to O(log N).
    
    Example:
        index = SpatialIndex()
        index.insert('agent_1', lat=55.9533, lon=-3.1883, radius_km=5.0)
        
        # Find agents within 10km of event
        nearby = index.query_radius(55.9600, -3.1900, radius_km=10.0)
    """
    
    def __init__(self, use_rtree: bool = True):
        """
        Initialize spatial index.
        
        Args:
            use_rtree: Use R-tree if available (default True)
        """
        self.use_rtree = use_rtree and RTREE_AVAILABLE
        
        if self.use_rtree:
            # R-tree index (fast!)
            self.rtree = rtree_index.Index()
            logger.info("✅ Using R-tree spatial index (O(log N) queries)")
        else:
            # Brute force fallback
            self.rtree = None
            logger.info("⚠️ Using brute force spatial index (O(N) queries)")
        
        # Store object data: {id: SpatialObject}
        self.objects: Dict[str, SpatialObject] = {}
        
        # For rtree: {internal_id: object_id} mapping
        self._rtree_id_counter = 0
        self._rtree_id_map: Dict[int, str] = {}
        self._object_to_rtree_id: Dict[str, int] = {}
    
    def insert(
        self,
        object_id: str,
        latitude: float,
        longitude: float,
        **metadata
    ):
        """
        Insert object into spatial index.
        
        Args:
            object_id: Unique identifier (e.g., 'agent_123')
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            **metadata: Additional data (e.g., perception_radius_km)
        """
        
        # Validate coordinates
        if not -90 <= latitude <= 90:
            raise ValueError(f"Invalid latitude: {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"Invalid longitude: {longitude}")
        
        # Create spatial object
        obj = SpatialObject(
            object_id=object_id,
            latitude=latitude,
            longitude=longitude,
            metadata=metadata
        )
        
        # Store object
        self.objects[object_id] = obj
        
        if self.use_rtree:
            # Insert into R-tree
            # R-tree uses bounding box: (minx, miny, maxx, maxy)
            # For point: (lon, lat, lon, lat)
            rtree_id = self._rtree_id_counter
            self._rtree_id_counter += 1
            
            bbox = (longitude, latitude, longitude, latitude)
            self.rtree.insert(rtree_id, bbox)
            
            # Store mapping
            self._rtree_id_map[rtree_id] = object_id
            self._object_to_rtree_id[object_id] = rtree_id
        
        logger.debug(f"📍 Inserted {object_id} at ({latitude:.4f}, {longitude:.4f})")
    
    def update(
        self,
        object_id: str,
        latitude: float,
        longitude: float,
        **metadata
    ):
        """
        Update object location (e.g., agent moved).
        
        Args:
            object_id: Object to update
            latitude: New latitude
            longitude: New longitude
            **metadata: Updated metadata
        """
        
        if object_id not in self.objects:
            raise ValueError(f"Object {object_id} not in index")
        
        # Remove old entry
        self.remove(object_id)
        
        # Insert new entry
        self.insert(object_id, latitude, longitude, **metadata)
        
        logger.debug(f"📍 Updated {object_id} to ({latitude:.4f}, {longitude:.4f})")
    
    def remove(self, object_id: str):
        """
        Remove object from index.
        
        Args:
            object_id: Object to remove
        """
        
        if object_id not in self.objects:
            return
        
        if self.use_rtree:
            # Remove from R-tree
            rtree_id = self._object_to_rtree_id[object_id]
            obj = self.objects[object_id]
            bbox = (obj.longitude, obj.latitude, obj.longitude, obj.latitude)
            self.rtree.delete(rtree_id, bbox)
            
            # Clean up mappings
            del self._rtree_id_map[rtree_id]
            del self._object_to_rtree_id[object_id]
        
        # Remove object
        del self.objects[object_id]
        
        logger.debug(f"🗑️ Removed {object_id}")
    
    def query_radius(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[SpatialObject]:
        """
        Find all objects within radius of point.
        
        Args:
            latitude: Query point latitude
            longitude: Query point longitude
            radius_km: Search radius in kilometers
        
        Returns:
            List of objects within radius
        """
        
        if self.use_rtree:
            return self._query_radius_rtree(latitude, longitude, radius_km)
        else:
            return self._query_radius_bruteforce(latitude, longitude, radius_km)
    
    def _query_radius_rtree(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[SpatialObject]:
        """R-tree based radius query (O(log N))."""
        
        # Convert radius to degrees (approximate)
        # 1 degree latitude ≈ 111 km
        # 1 degree longitude ≈ 111 * cos(latitude) km
        import math
        
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(latitude)))
        
        # Query bounding box
        min_lon = longitude - lon_delta
        max_lon = longitude + lon_delta
        min_lat = latitude - lat_delta
        max_lat = latitude + lat_delta
        
        bbox = (min_lon, min_lat, max_lon, max_lat)
        
        # Get candidates from R-tree (fast!)
        rtree_ids = list(self.rtree.intersection(bbox))
        
        # Filter candidates by actual distance (Haversine)
        results = []
        for rtree_id in rtree_ids:
            object_id = self._rtree_id_map[rtree_id]
            obj = self.objects[object_id]
            
            distance = self._haversine_distance(
                latitude, longitude,
                obj.latitude, obj.longitude
            )
            
            if distance <= radius_km:
                results.append(obj)
        
        logger.debug(
            f"🔍 R-tree query: {len(rtree_ids)} candidates → "
            f"{len(results)} within {radius_km}km"
        )
        
        return results
    
    def _query_radius_bruteforce(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[SpatialObject]:
        """Brute force radius query (O(N))."""
        
        results = []
        
        for obj in self.objects.values():
            distance = self._haversine_distance(
                latitude, longitude,
                obj.latitude, obj.longitude
            )
            
            if distance <= radius_km:
                results.append(obj)
        
        logger.debug(
            f"🔍 Brute force query: checked {len(self.objects)} objects → "
            f"{len(results)} within {radius_km}km"
        )
        
        return results
    
    @staticmethod
    def _haversine_distance(
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """
        Calculate great-circle distance using Haversine formula.
        
        Returns:
            Distance in kilometers
        """
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Earth radius in km
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        
        return R * c
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            'num_objects': len(self.objects),
            'index_type': 'rtree' if self.use_rtree else 'brute_force',
            'rtree_available': RTREE_AVAILABLE
        }
    
    def clear(self):
        """Clear all objects from index."""
        if self.use_rtree:
            # R-tree doesn't have clear(), recreate it
            self.rtree = rtree_index.Index()
            self._rtree_id_map.clear()
            self._object_to_rtree_id.clear()
            self._rtree_id_counter = 0
        
        self.objects.clear()
        logger.info("🗑️ Cleared spatial index")


# ==================================================================
# EXAMPLE USAGE
# ==================================================================

if __name__ == "__main__":
    import time
    
    logging.basicConfig(level=logging.INFO)
    
    print("="*70)
    print("🧪 SPATIAL INDEX DEMO")
    print("="*70)
    print()
    
    # Create index
    index = SpatialIndex()
    
    # Insert some agents across Scotland
    print("📍 Inserting agents...")
    agents = [
        ('agent_edinburgh_1', 55.9533, -3.1883),
        ('agent_edinburgh_2', 55.9500, -3.1900),
        ('agent_glasgow_1', 55.8642, -4.2518),
        ('agent_glasgow_2', 55.8700, -4.2600),
        ('agent_aberdeen_1', 57.1499, -2.0938),
        ('agent_inverness_1', 57.4778, -4.2247),
    ]
    
    for agent_id, lat, lon in agents:
        index.insert(agent_id, lat, lon, perception_radius_km=5.0)
        print(f"  ✅ {agent_id}: ({lat:.4f}, {lon:.4f})")
    
    print(f"\n📊 Index contains {len(index.objects)} objects")
    print()
    
    # Query 1: Events near Edinburgh
    print("="*70)
    print("🔍 QUERY 1: Who perceives event in Edinburgh?")
    print("="*70)
    event_lat, event_lon = 55.9533, -3.1883
    radius_km = 10.0
    
    print(f"Event at ({event_lat}, {event_lon}), radius={radius_km}km")
    
    start = time.time()
    nearby = index.query_radius(event_lat, event_lon, radius_km)
    elapsed = time.time() - start
    
    print(f"Found {len(nearby)} agents in {elapsed*1000:.2f}ms:")
    for obj in nearby:
        dist = index._haversine_distance(event_lat, event_lon, obj.latitude, obj.longitude)
        print(f"  📍 {obj.object_id}: {dist:.2f}km away")
    
    print()
    
    # Query 2: Events near Glasgow
    print("="*70)
    print("🔍 QUERY 2: Who perceives event in Glasgow?")
    print("="*70)
    event_lat, event_lon = 55.8642, -4.2518
    radius_km = 10.0
    
    print(f"Event at ({event_lat}, {event_lon}), radius={radius_km}km")
    
    start = time.time()
    nearby = index.query_radius(event_lat, event_lon, radius_km)
    elapsed = time.time() - start
    
    print(f"Found {len(nearby)} agents in {elapsed*1000:.2f}ms:")
    for obj in nearby:
        dist = index._haversine_distance(event_lat, event_lon, obj.latitude, obj.longitude)
        print(f"  📍 {obj.object_id}: {dist:.2f}km away")
    
    print()
    
    # Query 3: Wide radius (all of Scotland)
    print("="*70)
    print("🔍 QUERY 3: Nationwide event")
    print("="*70)
    event_lat, event_lon = 56.5, -3.5  # Center of Scotland
    radius_km = 200.0
    
    print(f"Event at ({event_lat}, {event_lon}), radius={radius_km}km")
    
    start = time.time()
    nearby = index.query_radius(event_lat, event_lon, radius_km)
    elapsed = time.time() - start
    
    print(f"Found {len(nearby)} agents in {elapsed*1000:.2f}ms:")
    for obj in nearby:
        dist = index._haversine_distance(event_lat, event_lon, obj.latitude, obj.longitude)
        print(f"  📍 {obj.object_id}: {dist:.2f}km away")
    
    print()
    
    # Performance test
    print("="*70)
    print("⚡ PERFORMANCE TEST")
    print("="*70)
    
    print("Adding 1000 agents...")
    import random
    
    for i in range(1000):
        lat = 55.0 + random.random() * 3.0  # 55-58°N (Scotland)
        lon = -5.0 + random.random() * 3.0  # -5 to -2°W
        index.insert(f'perf_agent_{i}', lat, lon)
    
    print(f"Index now contains {len(index.objects)} objects")
    print()
    
    # Query performance
    print("Running 100 radius queries...")
    start = time.time()
    
    for _ in range(100):
        lat = 55.0 + random.random() * 3.0
        lon = -5.0 + random.random() * 3.0
        nearby = index.query_radius(lat, lon, radius_km=10.0)
    
    elapsed = time.time() - start
    avg_time = elapsed / 100
    
    print(f"Average query time: {avg_time*1000:.2f}ms")
    print(f"Queries per second: {100/elapsed:.0f}")
    
    stats = index.get_statistics()
    print(f"\n📊 Final statistics: {stats}")
    
    print("\n✅ Demo complete!")