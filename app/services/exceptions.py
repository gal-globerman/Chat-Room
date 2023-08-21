class ServiceException(Exception):
    pass


class AuthenticationFail(ServiceException):
    pass


class TokenExpired(ServiceException):
    pass


class ResourceNotFound(ServiceException):
    pass


class PermissionDenied(ServiceException):
    pass


class MatchingPermissionDenied(PermissionDenied):
    pass


class MessagingPermissionDenied(PermissionDenied):
    pass
