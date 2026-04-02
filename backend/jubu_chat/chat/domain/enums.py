from enum import Enum

from jubu_datastore.common.enums import ConversationState  # re-export


class Sentiment(Enum):
    """Sentiment of the child."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
