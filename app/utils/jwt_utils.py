# app/utils/jwt_utils.py
from datetime import datetime, timedelta
from typing import Optional, Dict
from abc import ABC, abstractmethod
import jwt
from app.config import settings

# ===============================
# PRODUCT: JWTToken Class
# ===============================

class JWTToken:
    """
    Product class that wraps the JWT token string.
    Provides additional flexibility for future use like token metadata, printing, parsing, logging, etc.
    """

    def __init__(self, token: str):
        self.token = token

    def __str__(self):
        # Allows the token object to be used as a string
        return self.token


# ===============================
# ABSTRACT INTERFACE (Factory)
# ===============================

class JWTFactory(ABC):
    """
    Abstract base class defining the interface for a JWT Factory.
    This follows the Factory Design Pattern by declaring two key methods:
    - create_token: for encoding a JWT token
    - verify_token: for decoding and verifying a token

    Hides implementation from client auth/routes.py.
    Different token generation strategies (e.g., HS256, RS256) can subclass this.
    """

    @abstractmethod
    def create_token(self, data: Dict, expires_delta: Optional[timedelta] = None) -> JWTToken:
        """
        Abstract method to create a JWT token.
        :param data: Payload data to be encoded in the token
        :param expires_delta: Optional custom expiration time
        :return: Encoded JWT token as string
        """
        pass

    @abstractmethod
    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Abstract method to decode and verify a JWT token.
        :param token: Encoded JWT string
        :return: Decoded payload if valid; otherwise, None
        """
        pass


# =====================================================
# CONCRETE FACTORY IMPLEMENTATION: HS256 Algorithm
# =====================================================

class HS256JWTFactory(JWTFactory):
    """
    Concrete implementation of JWTFactory using HS256 algorithm.
    This encapsulates the token creation and verification logic, keeping it interchangeable with other factories (like RS256).
    HS256JWTFactory class is the actual factory, and jwt_factory variable is its instance.
    """

    def __init__(self):
        # Read secrets and algorithm from environment (via settings)
        self.secret_key = settings.SECRET_KEY
        self.algorithm = settings.ALGORITHM
        self.default_expiry = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    def create_token(self, data: Dict, expires_delta: Optional[timedelta] = None) -> JWTToken:
        """
        Creates a JWT token with the provided payload and expiration time.
        Adds an 'exp' (expiry) claim to the token.
        Encapsulation - holds internal logic and secrets (secret_key, algorithm).
        """
        to_encode = data.copy()

        # Set expiry time (custom or default)
        expire = datetime.utcnow() + (expires_delta or self.default_expiry)
        to_encode.update({"exp": expire})

        # Encode the token using PyJWT
        encoded = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded

    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Decodes and verifies a JWT token.
        Returns decoded payload if token is valid.
        Returns None if token is invalid or expired.
        """
        try:
            return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except jwt.PyJWTError:
            return None


# ======================================================
# SINGLETON FACTORY INSTANCE USED ACROSS THE APP
# ======================================================

# Instantiate the factory — this instance will be imported and used in route handlers.
# If you want to swap to RS256 (RS256JWTFactory) or any other token type in the future, just change the class here and no need to change routes.
jwt_factory = HS256JWTFactory()
