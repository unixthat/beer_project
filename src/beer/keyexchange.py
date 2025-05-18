# key exchange abstraction module

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def generate_key_pair() -> tuple[bytes, ec.EllipticCurvePrivateKey]:
    """Generate an ECDH key pair; return (public_bytes, private_key)"""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint
    )
    return public_bytes, private_key


def derive_session_key(private_key: ec.EllipticCurvePrivateKey, peer_public_bytes: bytes) -> bytes:
    """Derive a shared session key using ECDH and HKDF"""
    peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_public_bytes)
    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"beer-session"
    )
    return hkdf.derive(shared_secret)

# Placeholder for client/server handshake routines

def client_hello() -> tuple[bytes, ec.EllipticCurvePrivateKey]:
    """Initiate handshake: return client public key bytes and private key for later derivation"""
    # Generate ECDH key pair for client
    return generate_key_pair()


def server_hello(peer_pub: bytes) -> tuple[bytes, ec.EllipticCurvePrivateKey]:
    """Respond to handshake: return server public key bytes and private key for later derivation"""
    # Generate ECDH key pair for server
    return generate_key_pair()
