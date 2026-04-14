from passlib.context import CryptContext

# bcrypt has a 72-byte input limit. bcrypt_sha256 pre-hashes first and then
# uses bcrypt, so long user passwords are handled safely.
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)