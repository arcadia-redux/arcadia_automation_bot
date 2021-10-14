from enum import Enum, auto


class BotState(Enum):
    UNSET = 0
    SET = 1


class ApiRequestKind(Enum):
    POST = auto()
    GET = auto()
    PUT = auto()
    PATCH = auto()
    DELETE = auto()

    def __str__(self):
        return self.name.lower()
