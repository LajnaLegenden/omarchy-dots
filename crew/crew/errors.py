class CrewError(Exception):
    code = 1


class UsageError(CrewError):
    code = 2


class NotFoundError(CrewError):
    code = 3


class NothingDeliveredError(CrewError):
    code = 4


class TimeoutError_(CrewError):
    code = 5
