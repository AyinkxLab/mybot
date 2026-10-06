"""Handy generators: strong passwords and UUIDs."""


def register(api):
    import secrets
    import string
    import uuid

    def gen_password(length=20):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
        return "".join(secrets.choice(alphabet) for _ in range(int(length)))

    def gen_uuid():
        return str(uuid.uuid4())

    api.register_tool(
        "gen_password",
        gen_password,
        "Generate a strong random password.",
        {
            "type": "object",
            "properties": {"length": {"type": "integer"}},
            "required": [],
        },
    )
    api.register_tool(
        "gen_uuid",
        gen_uuid,
        "Generate a UUID v4.",
        {"type": "object", "properties": {}, "required": []},
    )
