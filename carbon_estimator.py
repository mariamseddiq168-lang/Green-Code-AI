# ============================================================
# Carbon Estimator
# ============================================================

# Default estimated carbon intensity.
# Unit: grams of CO2e per kWh
DEFAULT_CARBON_INTENSITY = 475.0

# 1 kWh = 3,600,000 Joules
JOULES_PER_KWH = 3_600_000


def joules_to_kwh(energy_joules: float) -> float:
    """
    Convert energy from Joules to kilowatt-hours (kWh).
    """

    if energy_joules < 0:
        raise ValueError(
            "Energy cannot be negative."
        )

    return energy_joules / JOULES_PER_KWH


def estimate_carbon(
    energy_joules: float,
    carbon_intensity: float = DEFAULT_CARBON_INTENSITY,
) -> float:
    """
    Estimate carbon emissions in grams of CO2e.

    Formula:

        Energy (kWh) =
            Energy (J) / 3,600,000

        Carbon (gCO2e) =
            Energy (kWh)
            × Carbon Intensity (gCO2e/kWh)
    """

    if energy_joules < 0:
        raise ValueError(
            "Energy cannot be negative."
        )

    if carbon_intensity < 0:
        raise ValueError(
            "Carbon intensity cannot be negative."
        )

    energy_kwh = joules_to_kwh(
        energy_joules
    )

    carbon_grams = (
        energy_kwh
        * carbon_intensity
    )

    return carbon_grams