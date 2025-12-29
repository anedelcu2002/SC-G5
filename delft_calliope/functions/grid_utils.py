import numpy as np

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points on Earth using the Haversine formula.
    
    Args:
        lat1, lon1: Latitude and longitude of first point in degrees
        lat2, lon2: Latitude and longitude of second point in degrees
    
    Returns:
        float: Distance in kilometers
    
    Note:
        Can handle vectorized numpy arrays for batch distance calculations.
    """
    R = 6371  # Earth radius in km
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def interpolate_line(lat1, lon1, lat2, lon2, spacing_m):
    """
    Interpolate points along a line segment at specified spacing.
    
    Args:
        lat1, lon1: Latitude and longitude of start point in degrees
        lat2, lon2: Latitude and longitude of end point in degrees
        spacing_m: Desired spacing between interpolated points in meters
    
    Returns:
        list of tuples: List of (latitude, longitude) tuples for interpolated points,
                       including start and end points
    """
    total_dist_km = haversine_distance(lat1, lon1, lat2, lon2)
    total_dist_m = total_dist_km * 1000
    
    if total_dist_m < 1e-6:
        return [(lat1, lon1), (lat2, lon2)]
    
    n_points = int(np.floor(total_dist_m / spacing_m))
    if n_points < 1:
        return [(lat1, lon1), (lat2, lon2)]
    
    lats = np.linspace(lat1, lat2, n_points + 2)
    lons = np.linspace(lon1, lon2, n_points + 2)
    return list(zip(lats, lons))
