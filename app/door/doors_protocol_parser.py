from __future__ import annotations


class DoorsProtocolParser:
    """Parses lines like '!DOORS;1=1;2=0;3=1' into {channel: value}."""

    PREFIX = "!DOORS"

    def parse(self, line: str) -> dict[int, int]:
        if not isinstance(line, str):
            raise ValueError("Door protocol line must be string")

        raw = line.strip()
        if not raw:
            raise ValueError("Door protocol line is empty")

        if raw == self.PREFIX:
            return {}

        prefix = f"{self.PREFIX};"
        if not raw.startswith(prefix):
            raise ValueError(f"Invalid door protocol prefix: {raw}")

        payload = raw[len(prefix):]
        if not payload:
            return {}

        result: dict[int, int] = {}
        for token in payload.split(";"):
            token = token.strip()
            if not token:
                raise ValueError("Door protocol contains empty token")
            if "=" not in token:
                raise ValueError(f"Door protocol token has no '=': {token}")
            channel_raw, value_raw = token.split("=", 1)
            channel_raw = channel_raw.strip()
            value_raw = value_raw.strip()
            if not channel_raw or not value_raw:
                raise ValueError(f"Invalid channel=value pair: {token}")

            channel = int(channel_raw)
            value = int(value_raw)
            result[channel] = value

        return result

