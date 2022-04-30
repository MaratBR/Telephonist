import binascii
import secrets


def mask(token: bytes):
    salt = secrets.token_bytes(1)
    xored = int.from_bytes(token, byteorder="big") ^ int.from_bytes(
        salt * len(token), byteorder="big"
    )
    masked = binascii.b2a_hex(
        salt + xored.to_bytes(len(token), byteorder="big")
    ).decode("ascii")
    return masked


def unmask(token: str):
    b = binascii.a2b_hex(token)
    salt = b[:1] * (len(b) - 1)
    unmasked = binascii.b2a_hex(
        (
            int.from_bytes(salt, byteorder="big")
            ^ int.from_bytes(b[1:], byteorder="big")
        ).to_bytes(len(b) - 1, byteorder="big")
    ).decode("ascii")
    return unmasked


def main():
    token = secrets.token_bytes(48)
    token_str = binascii.b2a_hex(token).decode("ascii")
    print(f"token_str = {token_str}")
    for i in range(100):
        masked = mask(token)
        print(f"masked = {masked}")
        unmasked = unmask(masked)
        assert unmasked == token_str


if __name__ == "__main__":
    main()
