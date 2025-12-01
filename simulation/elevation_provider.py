"""
Elevation data provider using OpenTopoMap and SRTM data.

Supports multiple free elevation data sources:
1. OpenTopoData API (free, no API key)
2. SRTM tiles (download and cache locally)
3. Mapzen/Nextzen tiles (optional)

Usage:
    provider = ElevationProvider(cache_dir=Path(".elevation_cache"))
    elevation = provider.get_elevation(lat=55.95, lon=-3.19)
    provider.add_elevation_to_graph(G)
"""

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Optional, Tuple, List
import pickle
import hashlib

logger = logging.getLogger(__name__)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests not available - install with: pip install requests")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


class ElevationProvider:
    """
    Multi-source elevation data provider.
    
    Priority order:
    1. Local cache (instant)
    2. OpenTopoData API (free, public)
    3. SRTM local tiles (if downloaded)
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path.home() / ".rtd_sim_cache" / "elevation"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache for session
        self._memory_cache = {}
        
        # API endpoints (all free, no key required)
        self.apis = {
            'opentopo': 'https://api.opentopodata.org/v1/srtm30m',
            'opentopo_ned': 'https://api.opentopodata.org/v1/ned10m',  # US only, higher res
            'opentopo_mapzen': 'https://api.opentopodata.org/v1/mapzen',
        }
        
        # Rate limiting (be nice to free APIs)
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
        
        logger.info(f"Elevation cache: {self.cache_dir}")
    
    def get_elevation(
        self, 
        lat: float, 
        lon: float, 
        api: str = 'opentopo'
    ) -> Optional[float]:
        """
        Get elevation for a single point.
        
        Args:
            lat: Latitude
            lon: Longitude  
            api: Which API to use ('opentopo', 'opentopo_ned', 'opentopo_mapzen')
        
        Returns:
            Elevation in meters, or None if unavailable
        """
        # Check memory cache
        cache_key = self._get_cache_key(lat, lon)
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]
        
        # Check disk cache
        disk_value = self._load_from_disk_cache(cache_key)
        if disk_value is not None:
            self._memory_cache[cache_key] = disk_value
            return disk_value
        
        # Fetch from API
        elevation = self._fetch_from_api(lat, lon, api)
        
        if elevation is not None:
            self._memory_cache[cache_key] = elevation
            self._save_to_disk_cache(cache_key, elevation)
        
        return elevation
    
    def get_elevations_batch(
        self, 
        coords: List[Tuple[float, float]], 
        api: str = 'opentopo',
        max_batch_size: int = 100
    ) -> List[Optional[float]]:
        """
        Get elevations for multiple points (batched for efficiency).
        
        Args:
            coords: List of (lat, lon) tuples
            api: Which API to use
            max_batch_size: Max points per API request
        
        Returns:
            List of elevations (same order as input)
        """
        if not coords:
            return []
        
        results = [None] * len(coords)
        
        # Check cache first
        uncached_indices = []
        for i, (lat, lon) in enumerate(coords):
            cache_key = self._get_cache_key(lat, lon)
            
            # Check memory
            if cache_key in self._memory_cache:
                results[i] = self._memory_cache[cache_key]
                continue
            
            # Check disk
            disk_value = self._load_from_disk_cache(cache_key)
            if disk_value is not None:
                self._memory_cache[cache_key] = disk_value
                results[i] = disk_value
                continue
            
            uncached_indices.append(i)
        
        if not uncached_indices:
            logger.info(f"All {len(coords)} elevations from cache")
            return results
        
        logger.info(f"Fetching {len(uncached_indices)} elevations from API...")
        
        # Batch fetch uncached points
        for batch_start in range(0, len(uncached_indices), max_batch_size):
            batch_indices = uncached_indices[batch_start:batch_start + max_batch_size]
            batch_coords = [coords[i] for i in batch_indices]
            
            batch_elevations = self._fetch_batch_from_api(batch_coords, api)
            
            for idx, elev in zip(batch_indices, batch_elevations):
                if elev is not None:
                    results[idx] = elev
                    lat, lon = coords[idx]
                    cache_key = self._get_cache_key(lat, lon)
                    self._memory_cache[cache_key] = elev
                    self._save_to_disk_cache(cache_key, elev)
        
        return results
    
    def add_elevation_to_graph(self, G, api: str = 'opentopo', show_progress: bool = True):
        """
        Add elevation attribute to all nodes in a NetworkX graph.
        
        Args:
            G: NetworkX graph (from OSMnx)
            api: Which API to use
            show_progress: Print progress updates
        
        Returns:
            Graph with 'elevation' attribute on nodes
        """
        if G is None:
            logger.warning("Graph is None")
            return G
        
        nodes = list(G.nodes(data=True))
        if not nodes:
            logger.warning("Graph has no nodes")
            return G
        
        logger.info(f"Adding elevation to {len(nodes)} nodes...")
        
        # Extract coordinates
        coords = []
        for node_id, data in nodes:
            lat = data.get('y')
            lon = data.get('x')
            if lat is not None and lon is not None:
                coords.append((lat, lon))
            else:
                coords.append(None)
        
        # Batch fetch elevations
        elevations = []
        valid_coords = [c for c in coords if c is not None]
        
        if valid_coords:
            valid_elevations = self.get_elevations_batch(valid_coords, api=api)
            
            # Map back to full list
            elev_iter = iter(valid_elevations)
            for c in coords:
                if c is None:
                    elevations.append(None)
                else:
                    elevations.append(next(elev_iter))
        else:
            elevations = [None] * len(coords)
        
        # Add to graph
        success_count = 0
        for (node_id, data), elev in zip(nodes, elevations):
            if elev is not None:
                G.nodes[node_id]['elevation'] = elev
                success_count += 1
        
        logger.info(f"✅ Added elevation to {success_count}/{len(nodes)} nodes")
        
        return G
    
    def _fetch_from_api(self, lat: float, lon: float, api: str) -> Optional[float]:
        """Fetch single elevation from API."""
        if not REQUESTS_AVAILABLE:
            logger.warning("requests library not available")
            return None
        
        url = self.apis.get(api)
        if url is None:
            logger.error(f"Unknown API: {api}")
            return None
        
        # Rate limiting
        self._rate_limit()
        
        try:
            params = {'locations': f'{lat},{lon}'}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') == 'OK' and data.get('results'):
                elevation = data['results'][0].get('elevation')
                return float(elevation) if elevation is not None else None
            else:
                logger.warning(f"API returned non-OK status: {data.get('status')}")
                return None
        
        except Exception as e:
            logger.warning(f"API request failed: {e}")
            return None
    
    def _fetch_batch_from_api(
        self, 
        coords: List[Tuple[float, float]], 
        api: str
    ) -> List[Optional[float]]:
        """Fetch multiple elevations in one API call."""
        if not REQUESTS_AVAILABLE:
            return [None] * len(coords)
        
        url = self.apis.get(api)
        if url is None:
            return [None] * len(coords)
        
        # Rate limiting
        self._rate_limit()
        
        try:
            # Format: "lat1,lon1|lat2,lon2|..."
            locations = '|'.join(f'{lat},{lon}' for lat, lon in coords)
            params = {'locations': locations}
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') == 'OK' and data.get('results'):
                results = []
                for result in data['results']:
                    elev = result.get('elevation')
                    results.append(float(elev) if elev is not None else None)
                return results
            else:
                logger.warning(f"Batch API returned non-OK: {data.get('status')}")
                return [None] * len(coords)
        
        except Exception as e:
            logger.warning(f"Batch API request failed: {e}")
            return [None] * len(coords)
    
    def _rate_limit(self):
        """Enforce rate limiting for API requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _get_cache_key(self, lat: float, lon: float) -> str:
        """Generate cache key for coordinate (rounded to ~10m precision)."""
        lat_round = round(lat, 4)
        lon_round = round(lon, 4)
        key_str = f"{lat_round},{lon_round}"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def _load_from_disk_cache(self, cache_key: str) -> Optional[float]:
        """Load elevation from disk cache."""
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)
            except Exception:
                pass
        return None
    
    def _save_to_disk_cache(self, cache_key: str, elevation: float):
        """Save elevation to disk cache."""
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(elevation, f)
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        cache_files = list(self.cache_dir.glob("*.pkl"))
        total_size = sum(f.stat().st_size for f in cache_files)
        
        return {
            "memory_cache_size": len(self._memory_cache),
            "disk_cache_files": len(cache_files),
            "disk_cache_size_mb": total_size / (1024**2),
            "cache_dir": str(self.cache_dir),
        }
    
    def clear_cache(self):
        """Clear disk cache."""
        for f in self.cache_dir.glob("*.pkl"):
            f.unlink()
        self._memory_cache.clear()
        logger.info("Cache cleared")


# ============================================================================
# Helper Functions
# ============================================================================

def test_elevation_provider():
    """Test the elevation provider with Edinburgh coordinates."""
    print("\n" + "="*60)
    print("Testing ElevationProvider")
    print("="*60)
    
    provider = ElevationProvider()
    
    # Test single point (Arthur's Seat, Edinburgh - should be ~250m)
    print("\n📍 Testing Arthur's Seat (Edinburgh)...")
    lat, lon = 55.9445, -3.1619
    elevation = provider.get_elevation(lat, lon)
    
    if elevation is not None:
        print(f"✅ Elevation: {elevation:.1f} m (expected ~250m)")
    else:
        print("❌ Failed to get elevation")
    
    # Test batch (Edinburgh Castle to Holyrood Palace)
    print("\n📍 Testing batch (5 points along Royal Mile)...")
    coords = [
        (55.9486, -3.2008),  # Edinburgh Castle
        (55.9506, -3.1930),
        (55.9526, -3.1870),
        (55.9540, -3.1800),
        (55.9520, -3.1730),  # Holyrood Palace
    ]
    
    elevations = provider.get_elevations_batch(coords)
    
    print(f"✅ Got {sum(e is not None for e in elevations)}/5 elevations:")
    for i, (coord, elev) in enumerate(zip(coords, elevations)):
        if elev is not None:
            print(f"   Point {i+1}: {elev:.1f} m")
    
    # Cache stats
    print("\n📊 Cache statistics:")
    stats = provider.get_cache_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n✅ Test complete")


if __name__ == "__main__":
    test_elevation_provider()