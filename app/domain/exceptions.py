class DomainException(Exception):
    pass


class DomainPermissionDenied(DomainException):
    pass


class MemberAlreadyJoined(DomainPermissionDenied):
    pass


class NumOfMemberHasReachedTheLimit(DomainPermissionDenied):
    pass


class MemberNotInThread(DomainException):
    pass
