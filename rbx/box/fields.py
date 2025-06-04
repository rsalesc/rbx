from pydantic import Field


def NameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=32, **kwargs
    )


def FNameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=128, **kwargs
    )
