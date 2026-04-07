import platform
import logging

logger = logging.getLogger(__name__)

# Cached after first call so non-Linux platforms don't re-stat the missing
# sysfs path on every poll.
_THERMAL_ZONE = "/sys/class/thermal/thermal_zone0/temp"
_PLATFORM = platform.system()


def get_cpu_temperature() -> float:
    """
    Return CPU temperature in Celsius.

    On Raspberry Pi / Linux this reads the standard thermal zone. On any
    other platform (macOS dev machines, Windows) we return a safe constant
    that will never trip the throttling threshold — there is no portable
    way to read CPU temp without an external dependency.
    """
    if _PLATFORM != "Linux":
        return 45.0
    try:
        with open(_THERMAL_ZONE, "r") as f:
            return int(f.read()) / 1000.0
    except OSError:
        return 0.0
