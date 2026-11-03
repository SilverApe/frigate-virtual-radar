"""Constants for Frigate Virtual Radar."""

DOMAIN = "frigate_virtual_radar"

CONF_CAMERA = "camera"
CONF_RADAR_NAME = "radar_name"
CONF_TOPIC = "topic"
CONF_MAX_TARGETS = "max_targets"
CONF_PERSON_LABELS = "person_labels"
CONF_DOG_LABEL = "dog_label"
CONF_MAX_DOGS = "max_dogs"
CONF_STALE_TIMEOUT = "stale_timeout"
CONF_MIN_MOVE = "min_move"
CONF_CALIBRATION = "calibration"

DEFAULT_TOPIC = "frigate/events"
DEFAULT_MAX_TARGETS = 3
DEFAULT_PERSON_LABELS = "person"
DEFAULT_DOG_LABEL = "dog"
DEFAULT_MAX_DOGS = 2
DEFAULT_STALE_TIMEOUT = 1800  # seconds; Frigate normally sends an "end" event long before this
DEFAULT_MIN_MOVE = 5  # cm; smaller movements are not written to the state machine

# RMM supports up to 5 targets per radar.
MAX_TARGETS_LIMIT = 5

GROUP_PERSON = "person"
GROUP_DOG = "dog"

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
