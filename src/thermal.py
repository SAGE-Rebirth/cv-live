import os
import platform
import logging

logger = logging.getLogger(__name__)

def get_cpu_temperature():
    """
    Returns API temperature in Celsius.
    Works on Raspberry Pi (Linux) and returns dummy on Mac.
    """
    try:
        if platform.system() == "Linux":
            # Standard Raspberry Pi thermal zone
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_str = f.read()
                return int(temp_str) / 1000.0
        elif platform.system() == "Darwin":
            # Mac doesn't expose standard temp easily without external tools (osx-cpu-temp)
            # returning safe dummy
            return 45.0
    except Exception:
        pass
    return 0.0
