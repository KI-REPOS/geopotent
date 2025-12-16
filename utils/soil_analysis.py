import requests
import logging
from typing import Dict, List, Optional, Any

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock soil data for testing when API is unavailable
MOCK_SOIL_DATA = {
    "phh2o": {
        "0-5cm": 64,  # pH 6.4
        "5-15cm": 63,  # pH 6.3
        "15-30cm": 65  # pH 6.5
    },
    "clay": {
        "0-5cm": 220,
        "5-15cm": 230,
        "15-30cm": 240
    },
    "sand": {
        "0-5cm": 450,
        "5-15cm": 440,
        "15-30cm": 430
    },
    "soc": {
        "0-5cm": 12,
        "5-15cm": 10,
        "15-30cm": 8
    },
    "nitrogen": {
        "0-5cm": 800,
        "5-15cm": 700,
        "15-30cm": 600
    }
}

# Mock Crop Data (Yield in kg/ha, Price in INR/kg)
CROP_DATA = {
    "Rice": {"yield": 4000, "price": 25},
    "Wheat": {"yield": 3500, "price": 22},
    "Maize": {"yield": 5000, "price": 20},
    "Cotton": {"yield": 2000, "price": 60},
    "Sugarcane": {"yield": 80000, "price": 3},  # High yield, low price per kg
    "Pulses (Chickpeas, Lentils, etc.)": {"yield": 1500, "price": 70},
    "Millets (Pearl millet, Finger millet, etc.)": {"yield": 2000, "price": 30},
    "Oilseeds (Groundnut, Sunflower, etc.)": {"yield": 2500, "price": 50},
    "Acid-tolerant crops (Potatoes, Blueberries, etc.)": {"yield": 25000, "price": 15},
    "Alkaline-tolerant crops (Asparagus, Beets, etc.)": {"yield": 15000, "price": 40},
    "Clay-soil crops (Rice, Wheat, etc.)": {"yield": 3800, "price": 24},
    "Sandy-soil crops (Groundnut, Millets, etc.)": {"yield": 2200, "price": 40},
    "Loam-soil crops (Most vegetables, grains, etc.)": {"yield": 10000, "price": 30},
    "General crops (adaptable to various soil conditions)": {"yield": 5000, "price": 25},
    "General crops suitable for diverse soil conditions": {"yield": 5000, "price": 25},
}


def get_soil_data(lat: float, lon: float, use_mock: bool = False) -> Optional[Dict]:
    """
    Fetch soil data from SoilGrids API for given coordinates

    Args:
        lat (float): Latitude
        lon (float): Longitude
        use_mock (bool): Whether to use mock data instead of API call

    Returns:
        dict: Soil properties data or None if request fails
    """
    if use_mock:
        logger.info("Using mock soil data")
        return MOCK_SOIL_DATA

    url = "https://rest.isric.org/soilgrids/v2.0/properties/query"

    # Define the properties and depths we're interested in
    params = {
        "lat": lat,
        "lon": lon,
        "property": "phh2o,clay,sand,soc,nitrogen",
        "depth": "0-5cm,5-15cm,15-30cm",
        "value": "mean"
    }

    try:
        logger.info(f"Requesting soil data from SoilGrids API for coordinates: {lat}, {lon}")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            logger.warning(f"API returned status code {response.status_code}. Using mock data instead.")
            return MOCK_SOIL_DATA

        data = response.json()

        soil_info = {}
        for prop in data.get("properties", {}).get("layers", []):
            name = prop["name"]
            soil_info[name] = {}
            for depth in prop["depths"]:
                values = depth["values"]
                # Use mean value if available
                value = values.get("mean")
                if value is not None:
                    soil_info[name][depth["label"]] = value

        return soil_info

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching soil data: {e}. Using mock data instead.")
        return MOCK_SOIL_DATA
    except (KeyError, ValueError) as e:
        logger.error(f"Error parsing soil data: {e}. Using mock data instead.")
        return MOCK_SOIL_DATA


def calculate_weighted_average(soil_data: Dict, property_name: str, depths_weights: Dict) -> Optional[float]:
    """
    Calculate weighted average of a soil property across depths

    Args:
        soil_data (dict): Soil data dictionary
        property_name (str): Name of the soil property
        depths_weights (dict): Dictionary with depth as key and weight as value

    Returns:
        float: Weighted average value or None if data is missing
    """
    if property_name not in soil_data:
        return None

    total_weight = 0
    weighted_sum = 0

    for depth, weight in depths_weights.items():
        if depth in soil_data[property_name]:
            value = soil_data[property_name][depth]
            if value is not None:
                weighted_sum += value * weight
                total_weight += weight

    if total_weight == 0:
        return None

    return weighted_sum / total_weight


def recommend_crops(soil_data: Dict) -> List[str]:
    """
    Recommend crops based on soil properties

    Args:
        soil_data (dict): Soil properties data

    Returns:
        list: Recommended crops
    """
    if not soil_data:
        return ["Unable to get soil data for recommendation"]

    recommendations = []

    # Define weights for depth layers (0-30cm average)
    depth_weights = {"0-5cm": 0.25, "5-15cm": 0.35, "15-30cm": 0.40}

    # Extract weighted average values for top 30cm
    try:
        # pH needs to be divided by 10 to get actual pH value
        if "phh2o" in soil_data:
            ph_data = {depth: value / 10 for depth, value in soil_data["phh2o"].items()}
            ph = calculate_weighted_average({"phh2o": ph_data}, "phh2o", depth_weights)
        else:
            ph = None

        clay = calculate_weighted_average(soil_data, "clay", depth_weights)
        sand = calculate_weighted_average(soil_data, "sand", depth_weights)
        organic_carbon = calculate_weighted_average(soil_data, "soc", depth_weights)
        nitrogen = calculate_weighted_average(soil_data, "nitrogen", depth_weights)

        # Check if we have all required data
        if any(v is None for v in [ph, clay, sand, organic_carbon, nitrogen]):
            missing = []
            if ph is None: missing.append("pH")
            if clay is None: missing.append("clay")
            if sand is None: missing.append("sand")
            if organic_carbon is None: missing.append("organic carbon")
            if nitrogen is None: missing.append("nitrogen")

            logger.warning(f"Missing soil parameters: {', '.join(missing)}. Using fallback recommendations.")
            return get_fallback_recommendations(soil_data)

        logger.info(f"Soil parameters - pH: {ph:.2f}, Clay: {clay:.1f} g/kg, "
                    f"Sand: {sand:.1f} g/kg, OC: {organic_carbon:.1f} g/kg, "
                    f"N: {nitrogen:.1f} mg/kg")

        # --- Crop recommendation logic ---
        # Rice: Prefers slightly acidic to neutral pH, high clay content for water retention
        if 5.5 <= ph <= 7.0 and clay > 250:
            recommendations.append("Rice")

        # Wheat: Prefers neutral pH, well-drained loamy soils
        if 6.0 <= ph <= 7.5 and 150 <= clay <= 350:
            recommendations.append("Wheat")

        # Maize: Prefers slightly acidic to neutral pH, well-drained soils
        if 5.8 <= ph <= 7.5 and sand > 200 and organic_carbon > 8:
            recommendations.append("Maize")

        # Cotton: Prefers neutral to slightly alkaline pH, well-drained soils
        if 6.0 <= ph <= 8.0 and 150 <= clay <= 400:
            recommendations.append("Cotton")

        # Pulses: Generally adaptable but prefer well-drained soils
        if 6.0 <= ph <= 7.5 and sand > 200:
            recommendations.append("Pulses (Chickpeas, Lentils, etc.)")

        # Sugarcane: Prefers slightly acidic to neutral pH, high organic matter
        if 6.0 <= ph <= 7.5 and organic_carbon > 10 and clay > 200:
            recommendations.append("Sugarcane")

        # Millets: Tolerant to acidic soils and low fertility
        if 5.5 <= ph <= 7.0 and sand > 300:
            recommendations.append("Millets (Pearl millet, Finger millet, etc.)")

        # Oilseeds: Various oilseeds have different preferences
        if 6.0 <= ph <= 7.0:
            recommendations.append("Oilseeds (Groundnut, Sunflower, etc.)")

        # Add fallback option if no specific recommendations
        if not recommendations:
            recommendations.append("General crops (adaptable to various soil conditions)")

    except KeyError as e:
        logger.error(f"Missing soil property in data: {e}")
        return ["Incomplete soil data for accurate recommendation"]

    return recommendations

def estimate_agri_revenue(crops: List[str], area_ha: float) -> Dict[str, Any]:
    """
    Estimate revenue for recommended crops.
    Returns the best performing crop and detailed list.
    """
    if not crops or area_ha <= 0:
        return {"best_crop": None, "max_revenue": 0, "details": []}

    details = []
    max_revenue = 0
    best_crop = None

    for crop in crops:
        data = CROP_DATA.get(crop, {"yield": 3000, "price": 20}) # Default fallback
        total_yield = data["yield"] * area_ha
        revenue = total_yield * data["price"]
        
        details.append({
            "crop": crop,
            "yield_kg": total_yield,
            "price_per_kg": data["price"],
            "revenue": revenue
        })

        if revenue > max_revenue:
            max_revenue = revenue
            best_crop = crop

    return {
        "best_crop": best_crop,
        "max_revenue": max_revenue,
        "details": details
    }

def estimate_agri_revenue(crops: List[str], area_ha: float) -> Dict[str, Any]:
    """
    Estimate revenue for recommended crops.
    Returns the best performing crop and detailed list.
    """
    if not crops or area_ha <= 0:
        return {"best_crop": None, "max_revenue": 0, "details": []}

    details = []
    max_revenue = 0
    best_crop = None

    for crop in crops:
        data = CROP_DATA.get(crop, {"yield": 3000, "price": 20}) # Default fallback
        total_yield = data["yield"] * area_ha
        revenue = total_yield * data["price"]
        
        details.append({
            "crop": crop,
            "yield_kg": total_yield,
            "price_per_kg": data["price"],
            "revenue": revenue
        })

        if revenue > max_revenue:
            max_revenue = revenue
            best_crop = crop

    return {
        "best_crop": best_crop,
        "max_revenue": max_revenue,
        "details": details
    }


def get_fallback_recommendations(soil_data: Dict) -> List[str]:
    """
    Provide fallback crop recommendations when soil data is incomplete

    Args:
        soil_data (dict): Partial soil data

    Returns:
        list: General crop recommendations
    """
    # Try to extract whatever data we have
    recommendations = []

    # If we have pH data, use it
    if "phh2o" in soil_data:
        try:
            # Get average pH from available depths
            ph_values = [v / 10 for v in soil_data["phh2o"].values()]
            avg_ph = sum(ph_values) / len(ph_values)

            if avg_ph < 5.5:
                recommendations.append("Acid-tolerant crops (Potatoes, Blueberries, etc.)")
            elif 5.5 <= avg_ph <= 7.0:
                recommendations.append("Most common crops (Rice, Wheat, Maize, etc.)")
            else:
                recommendations.append("Alkaline-tolerant crops (Asparagus, Beets, etc.)")
        except:
            pass

    # If we have texture data, use it
    if "clay" in soil_data or "sand" in soil_data:
        try:
            # Try to estimate texture
            clay_values = list(soil_data.get("clay", {}).values()) or [0]
            sand_values = list(soil_data.get("sand", {}).values()) or [0]

            avg_clay = sum(clay_values) / len(clay_values)
            avg_sand = sum(sand_values) / len(sand_values)

            if avg_clay > 400:
                recommendations.append("Clay-soil crops (Rice, Wheat, etc.)")
            elif avg_sand > 500:
                recommendations.append("Sandy-soil crops (Groundnut, Millets, etc.)")
            else:
                recommendations.append("Loam-soil crops (Most vegetables, grains, etc.)")
        except:
            pass

    if not recommendations:
        recommendations.append("General crops suitable for diverse soil conditions")

    return recommendations