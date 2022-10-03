from tomlkit.exceptions import TOMLKitError

from conda_lock.vendor.poetry_core.exceptions import PoetryCoreException


class TOMLError(TOMLKitError, PoetryCoreException):
    pass
